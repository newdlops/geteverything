"""Durable, leased jobs. Model suggestions require an explicit promotion gate."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import os
from pathlib import Path
import signal
import time

from . import context, rules, taxonomy
from .llm import InvalidResult, LocalModel, PROMPT_VERSION, Unavailable

RULE_VERSION = taxonomy.VERSION + '/' + rules.VERSION
STOP = False


def setup():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gadmin.categories.settings')
    import django
    django.setup()


def claim(stage):
    from django.db import transaction
    from django.db.models import Q
    from django.utils import timezone
    from gadmin.deals.models import DealClassification
    now = timezone.now()
    with transaction.atomic():
        job = (DealClassification.objects.select_for_update(skip_locked=True)
               .filter(status=stage, manual_override=False, next_attempt_at__lte=now)
               .filter(Q(lease_until__isnull=True) | Q(lease_until__lt=now))
               .order_by('priority', '-deal_id').first())
        if job is None:
            return None
        job.lease_until = now + timedelta(seconds=300)
        job.save(update_fields=['lease_until'])
        return job


def finish(job, **values):
    from gadmin.deals.models import DealClassification
    return DealClassification.objects.filter(deal_id=job.deal_id, request_revision=job.request_revision,
        input_title=job.input_title, manual_override=False).update(lease_until=None, **values)


def process_rule(job, llm_backfill=False):
    from django.utils import timezone
    from gadmin.deals.models import DealClassification
    metadata = context.inputs(job.deal)
    fingerprint = context.fingerprint(job.input_title, **metadata)
    cached = DealClassification.objects.filter(title_hash=fingerprint, classifier_version=RULE_VERSION,
        status='ready', source='rule', manual_override=False).exclude(category='').first()
    decision = rules.Decision(cached.category, cached.reason) if cached else context.classify(job.input_title, **metadata)
    return finish(job, category=decision.category, candidate='', source='rule' if decision.category else '',
        status='ready' if decision.category else ('review' if decision.reason in ('unavailable_title', 'promotion_only') or (job.priority == 10 and not llm_backfill) else 'llm'),
        title_hash=fingerprint, classifier_version=RULE_VERSION, reason=decision.reason,
        classified_at=timezone.now() if decision.category else None, last_error='', attempts=0)


def process_llm(job, model, version, publish=False):
    from django.utils import timezone
    from gadmin.deals.models import DealClassification
    fingerprint = rules.title_hash(job.input_title)
    cached = (DealClassification.objects.filter(title_hash=fingerprint, classifier_version=version,
        source='llm', status__in=['ready', 'review'], manual_override=False).exclude(deal_id=job.deal_id).first())
    try:
        category = (cached.category or cached.candidate) if cached else model.classify(job.input_title)
    except Unavailable:
        # An intentionally unloaded model is not a bad title and must not exhaust retries.
        return finish(job, next_attempt_at=timezone.now() + timedelta(seconds=60), last_error='model_unavailable')
    except InvalidResult as exc:
        attempts = job.attempts + 1
        return finish(job, attempts=attempts, status='error' if attempts >= 3 else 'llm',
                      last_error=str(exc), next_attempt_at=timezone.now() + timedelta(seconds=60 * 2**attempts))
    return finish(job, category=category if publish else '', candidate=category, source='llm',
        status='ready' if publish and category else 'review', title_hash=fingerprint, classifier_version=version,
        reason='local_model' if category else 'model_abstained', classified_at=timezone.now(), last_error='')


def enqueue_backfill(limit=100):
    from django.db import transaction
    from django.utils import timezone
    from gadmin.deals.models import ClassificationState, Deal, DealClassification
    if DealClassification.objects.filter(status='pending', priority=10).count() >= 200:
        return
    with transaction.atomic():
        state, _ = ClassificationState.objects.select_for_update().get_or_create(key='backfill', defaults={'value': {'cursor': (Deal.objects.order_by('-id').values_list('id', flat=True).first() or 0) + 1, 'scanned': 0, 'phase': 'scanning'}})
        value = state.value
        if value['phase'] == 'queued' and not DealClassification.objects.filter(status='pending', priority=10).exists():
            value.update(phase='rules_complete', completed_at=time.time())
            state.value = value
            state.save(update_fields=['value'])
        if value['phase'] != 'scanning':
            return
        # Row locks keep an old seed title from racing a concurrent crawler update.
        rows = list(Deal.objects.select_for_update().filter(id__lt=value['cursor']).order_by('-id').values_list('id', 'subject')[:limit])
        now = timezone.now()
        DealClassification.objects.bulk_create([DealClassification(deal_id=identity, input_title=title or '', priority=10, requested_at=now, next_attempt_at=now) for identity, title in rows], ignore_conflicts=True)
        if rows:
            value['cursor'] = rows[-1][0]
            value['scanned'] += len(rows)
        else:
            value['phase'] = 'queued'
        state.value = value
        state.save(update_fields=['value'])


def enqueue_rule_upgrade(limit=100):
    from django.db import transaction
    from django.db.models import F, Q
    from django.utils import timezone
    from gadmin.deals.models import ClassificationState, DealClassification
    if DealClassification.objects.filter(status='pending', priority=10).count() >= 100:
        return
    with transaction.atomic():
        state, _ = ClassificationState.objects.select_for_update().get_or_create(key='upgrade:'+RULE_VERSION,
            defaults={'value':{'phase':'scanning','queued':0}})
        value = state.value
        if value['phase'] != 'scanning':
            return
        ids = list(DealClassification.objects.select_for_update(skip_locked=True).filter(manual_override=False)
            .filter(Q(classifier_version__contains='/rules-')|Q(source='llm')).exclude(classifier_version=RULE_VERSION)
            .exclude(status='pending').order_by('-deal_id').values_list('deal_id',flat=True)[:limit])
        if ids:
            DealClassification.objects.filter(pk__in=ids).update(status='pending',priority=10,lease_until=None,
                attempts=0,request_revision=F('request_revision')+1,requested_at=timezone.now(),next_attempt_at=timezone.now())
            value['queued'] += len(ids)
        else:
            value.update(phase='queued',completed_at=time.time())
        state.value = value
        state.save(update_fields=['value'])


def status():
    from django.db.models import Count
    from gadmin.deals.models import ClassificationState, DealClassification, DealMeasurements, DealProduct
    counts = list(DealClassification.objects.values('status', 'source').annotate(count=Count('deal_id')).order_by('status', 'source'))
    return {'at': time.time(), 'counts': counts,
            'products':list(DealProduct.objects.values('status','source').annotate(count=Count('deal_id')).order_by('status','source')),
            'product_states':dict(ClassificationState.objects.filter(key__startswith='products:').values_list('key','value')),
            'measurements':list(DealMeasurements.objects.values('status').annotate(count=Count('deal_id')).order_by('status')),
            'measurements_backfill':ClassificationState.objects.filter(key='measurements-backfill').values_list('value',flat=True).first(),
            'rule_upgrade':ClassificationState.objects.filter(key='upgrade:'+RULE_VERSION).values_list('value',flat=True).first(),
            'backfill': ClassificationState.objects.filter(key='backfill').values_list('value', flat=True).first(),
            'worker': ClassificationState.objects.filter(key='worker').values_list('value', flat=True).first()}


def write_demand(path, count):
    if path:
        target = Path(path)
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps({'at': time.time(), 'pending': count}))
        os.replace(temporary, target)


def stop(*args):
    global STOP
    STOP = True


def model_task(job, model, version, publish, product=False):
    from django.db import close_old_connections
    close_old_connections()
    try:
        if product:
            from gadmin.products import jobs
            return jobs.process_llm(job,model)
        return process_llm(job, model, version, publish)
    finally:
        close_old_connections()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    setup()
    if args.status:
        print(json.dumps(status(), ensure_ascii=False))
        return
    from django.db import close_old_connections
    from django.utils import timezone
    from gadmin.deals.models import ClassificationState, DealClassification, DealProduct
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    model = LocalModel(os.environ.get('CATEGORY_LLM_ENDPOINT', 'http://127.0.0.1:8094'),timeout=240)
    version = taxonomy.VERSION + '/' + PROMPT_VERSION + '/' + os.environ.get('CATEGORY_MODEL_REVISION', 'unconfigured')
    enabled = os.environ.get('CATEGORY_LLM_ENABLED', '0') == '1'
    publish = os.environ.get('CATEGORY_LLM_AUTO_PUBLISH', '0') == '1'
    llm_backfill = os.environ.get('CATEGORY_LLM_BACKFILL', '0') == '1'
    maintenance = 0
    from gadmin.metrics import jobs as measurement_jobs, fx
    from gadmin.products import jobs as product_jobs
    from gadmin.products import backfill as product_backfill
    from gadmin.products import sources as product_sources
    from datetime import datetime
    fx_snapshot = fx.latest()
    fx_due = 0 if not fx_snapshot else max(0, 21600-(time.time()-datetime.fromisoformat(fx_snapshot['fetched_at']).timestamp())) + time.monotonic()
    # Slow model HTTP requests must not hold up rules for newly crawled titles.
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix='deal-enrichment') as pool:
        pending_model = None
        product_turn = True
        pending_fx = None
        pending_source = None
        source_due = 0
        while not STOP:
            close_old_connections()
            if pending_source is not None and pending_source.done():
                try:
                    pending_source.result()
                except Exception as exc:
                    print(json.dumps({'source_resolver_error': type(exc).__name__}), flush=True)
                pending_source = None
            if not args.once and pending_source is None and time.monotonic() >= source_due:
                pending_source = pool.submit(product_sources.resolve_redirects_once)
                source_due = time.monotonic() + 60
            if pending_fx is not None and pending_fx.done():
                try:
                    rate_date = pending_fx.result()
                    fx_result = {'at':time.time(),'status':'ready','date':rate_date}
                    fx_due = time.monotonic()+21600
                except Exception as exc:
                    fx_result = {'at':time.time(),'status':'error','error':type(exc).__name__}
                    fx_due = time.monotonic()+3600
                ClassificationState.objects.update_or_create(key='fx:worker',defaults={'value':fx_result})
                pending_fx = None
            if not args.once and pending_fx is None and time.monotonic() >= fx_due:
                pending_fx = pool.submit(fx.refresh)
            if pending_model is not None and pending_model.done():
                pending_model.result()
                pending_model = None
            if time.monotonic() >= maintenance:
                enqueue_backfill()
                enqueue_rule_upgrade()
                measurement_jobs.backfill()
                product_jobs.backfill()
                product_sources.backfill()
                product_sources.collect_pending()
                product_sources.revisit_waiting()
                product_backfill.maintenance()
                product_jobs.refill_model_queue()
                product_jobs.train_if_changed()
                category_pending=DealClassification.objects.filter(status='llm').count()
                product_pending=DealProduct.objects.filter(status='llm').count()
                pending = category_pending+product_pending
                write_demand(os.environ.get('CATEGORY_DEMAND_FILE'), pending if enabled else 0)
                ClassificationState.objects.update_or_create(key='worker', defaults={'value': {'at': time.time(), 'llm_enabled': enabled, 'llm_auto_publish': publish, 'model': version, 'pending_model': pending,'category_pending':category_pending,'product_pending':product_pending}})
                print(json.dumps({'at': timezone.now().isoformat(), 'pending_model': pending}), flush=True)
                maintenance = time.monotonic() + 15
            did_work = False
            for _ in range(50):
                if STOP:
                    break
                job = claim('pending')
                if job is None:
                    break
                try:
                    process_rule(job, llm_backfill)
                except (ValueError, TypeError, KeyError) as exc:
                    finish(job, status='error', last_error='rule_' + type(exc).__name__)
                did_work = True
            if measurement_jobs.process_batch():
                did_work = True
            product_rules=product_jobs.process_rules()
            product_prices=product_jobs.process_prices()
            if product_rules or product_prices:did_work = True
            if enabled and not STOP and pending_model is None:
                product=product_turn
                job = product_jobs.claim('llm') if product else claim('llm')
                if job is None:
                    product=not product
                    job=product_jobs.claim('llm') if product else claim('llm')
                if job is not None:
                    pending_model = pool.submit(model_task, job, model, version, publish,product)
                    product_turn=not product
                    did_work = True
            if args.once:
                if pending_model is not None:
                    pending_model.result()
                break
            time.sleep(1 if did_work else 3)


if __name__ == '__main__':
    main()
