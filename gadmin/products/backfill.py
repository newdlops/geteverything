"""A bounded rule upgrade and cache reuse pass, separate from price snapshots."""
from datetime import timedelta
import time

from django.db import transaction
from django.db.models import Count, Exists, F, OuterRef, Q
from django.utils import timezone

from gadmin.deals.models import ClassificationState, DealProduct
from . import identity, jobs

KEY='products:identity-backfill:'+jobs.VERSION
RULE_QUEUE_LIMIT=200


def stale(query):
    return query.filter(product=None,manual_override=False).filter(
        ~Q(processor_version=jobs.VERSION)|
        (Q(status='pending',last_error='awaiting_model_capacity')&~Q(extraction__has_key='attributes')))


def enqueue(limit=200):
    """Revisit old waits/reviews once with current rules. Never interrupt a lease."""
    limit=max(1,min(limit,RULE_QUEUE_LIMIT))
    now=timezone.now()
    with transaction.atomic():
        state,created=ClassificationState.objects.select_for_update().get_or_create(key=KEY,defaults={'value':{}})
        value=dict(state.value)
        if created or not value:
            ceiling=DealProduct.objects.order_by('-pk').values_list('pk',flat=True).first() or 0
            cohort=DealProduct.objects.filter(pk__lte=ceiling)
            value={'version':jobs.VERSION,'ceiling':ceiling,'started_at':time.time(),'queued':0,
                   'stale_at_start':stale(cohort).count(),'total_at_start':cohort.count(),
                   'linked_at_start':cohort.filter(status='ready',product__isnull=False,manual_override=False).count()}
        available=max(0,RULE_QUEUE_LIMIT-DealProduct.objects.filter(status='pending',manual_override=False)
                      .exclude(last_error='awaiting_model_capacity').count())
        ids=[]
        if available:
            ids=list(stale(DealProduct.objects.select_for_update(skip_locked=True).filter(pk__lte=value['ceiling']))
                .filter(Q(lease_until=None)|Q(lease_until__lte=now)).order_by('priority','-deal_id')
                .values_list('pk',flat=True)[:min(limit,available)])
            DealProduct.objects.filter(pk__in=ids).update(status='pending',processor_version=jobs.VERSION,
                last_error='backfill_rule_upgrade',lease_until=None,attempts=0,next_attempt_at=now,
                request_revision=F('request_revision')+1,processed_at=None)
        value['queued']+=len(ids)
        value['at']=time.time()
        state.value=value;state.save(update_fields=['value'])
    return len(ids)


def reuse_cached(limit=100):
    """Resolve exact, unambiguous cached identities without waiting for an LLM slot."""
    limit=max(1,min(limit,100))
    ready=DealProduct.objects.filter(input_hash=OuterRef('input_hash'),processor_version=jobs.VERSION,
        extraction__attributes=OuterRef('extraction__attributes'),status='ready',manual_override=False,
        product__is_active=True).order_by().values('input_hash').annotate(products=Count('product_id',distinct=True)).filter(products=1)
    now=timezone.now()
    with transaction.atomic():
        rows=list(DealProduct.objects.select_for_update(skip_locked=True).filter(
            product=None,manual_override=False,processor_version=jobs.VERSION)
            .filter(Q(status='pending',last_error='awaiting_model_capacity')|Q(status='llm'))
            .filter(Q(lease_until=None)|Q(lease_until__lte=now)).filter(Exists(ready))
            .order_by('priority','-deal_id')[:limit])
        for row in rows:
            row.request_revision+=1
            row.lease_until=now+timedelta(seconds=300)
        DealProduct.objects.bulk_update(rows,['request_revision','lease_until'])
    linked=0
    for row in rows:
        cached=jobs.cached_product(row.input_title)
        if cached and not identity.offer_issue(row.input_title):
            linked+=jobs.resolve(row,cached.extraction,cached.source,target=cached.product)
        else:
            jobs.finish(row)  # A changed title/cache must not leave a lease behind.
    return linked


def refresh_status():
    with transaction.atomic():
        state=ClassificationState.objects.select_for_update().filter(pk=KEY).first()
        if not state:return {}
        value=dict(state.value)
        cohort=DealProduct.objects.filter(pk__lte=value['ceiling'],manual_override=False)
        counts=cohort.aggregate(
            total=Count('pk'),linked=Count('pk',filter=Q(status='ready',product__isnull=False)),
            rules_pending=Count('pk',filter=Q(status='pending')&~Q(last_error='awaiting_model_capacity')),
            model_waiting=Count('pk',filter=Q(status='pending',last_error='awaiting_model_capacity')),
            model_queued=Count('pk',filter=Q(status='llm')),
            review=Count('pk',filter=Q(status='review')),errors=Count('pk',filter=Q(status='error')),
            rules_checked=Count('pk',filter=Q(processor_version=jobs.VERSION)&~Q(last_error='backfill_rule_upgrade')))
        remaining=stale(cohort).count()
        phase=('rules' if remaining or counts['rules_pending'] else 'model' if counts['model_waiting'] or counts['model_queued']
               else 'review' if counts['review'] or counts['errors'] else 'complete')
        value.update(**counts,stale_remaining=remaining,phase=phase,at=time.time(),
                     linked_since_start=counts['linked']-value['linked_at_start'])
        if phase!='rules' and not value.get('rules_completed_at'):value['rules_completed_at']=time.time()
        state.value=value;state.save(update_fields=['value'])
        return value


def maintenance(limit=200):
    queued=enqueue(limit)
    reused=reuse_cached()
    result=refresh_status()
    return {**result,'queued_this_batch':queued,'reused_this_batch':reused}
