"""Paced rule reclassification without a historical model-inference backlog."""
import argparse
import json
import time

from . import context
from .worker import RULE_VERSION, setup


def process_batch(limit=25, before=None):
    from django.db import transaction
    from django.utils import timezone
    from gadmin.deals.models import DealClassification

    with transaction.atomic():
        # Do not lock Deal: the crawler locks it before its classification trigger.
        # Context changes bump request_revision in that trigger after we commit.
        query = (DealClassification.objects.select_related('deal').select_for_update(of=('self',), skip_locked=True)
                 .filter(manual_override=False).exclude(classifier_version=RULE_VERSION)
                 .exclude(status='pending', priority=0))
        if before is not None:
            query = query.filter(deal_id__lt=before)
        rows = list(query.order_by('-deal_id')[:limit])
        now = timezone.now()
        for job in rows:
            metadata = context.inputs(job.deal)
            decision = context.classify(job.input_title, **metadata)
            job.category = decision.category
            job.reason = decision.reason
            job.candidate = ''
            job.source = 'rule' if decision.category else ''
            job.status = 'ready' if decision.category else 'review'
            job.classifier_version = RULE_VERSION
            job.title_hash = context.fingerprint(job.input_title, **metadata)
            # Invalidate a model/rule result claimed before this transaction.
            job.request_revision += 1
            job.lease_until = None
            job.attempts = 0
            job.last_error = ''
            job.classified_at = now if decision.category else None
            job.next_attempt_at = now
        if rows:
            DealClassification.objects.bulk_update(rows, [
                'category','reason','candidate','source','status','classifier_version',
                'title_hash','request_revision','lease_until','attempts','last_error',
                'classified_at','next_attempt_at'], batch_size=100)
        return len(rows), rows[-1].deal_id if rows else before


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--max-rows',type=int,default=50000)
    parser.add_argument('--batch-size',type=int,default=25)
    parser.add_argument('--pause',type=float,default=0.2)
    args = parser.parse_args()
    if not (1 <= args.max_rows <= 100000 and 1 <= args.batch_size <= 200 and 0.1 <= args.pause <= 10):
        parser.error('Use 1–100000 rows, 1–200 rows per batch, and a 0.1–10 second pause.')
    setup()
    from django.db import close_old_connections
    from gadmin.deals.models import ClassificationState
    done = 0
    cursor = None
    started = time.monotonic()
    while done < args.max_rows and time.monotonic()-started < 900:
        close_old_connections()
        count,cursor = process_batch(min(args.batch_size,args.max_rows-done),cursor)
        if not count:
            break
        done += count
        if done % 1000 == 0:
            print(json.dumps({'processed':done,'cursor':cursor}),flush=True)
        time.sleep(args.pause)
    # Let the normal small-batch upgrade pick up any rows skipped by row locks.
    ClassificationState.objects.update_or_create(key='upgrade:'+RULE_VERSION,defaults={'value':{
        'phase':'scanning','queued':0,'bulk_processed':done,'bulk_finished_at':time.time()}})
    print(json.dumps({'version':RULE_VERSION,'processed':done,'seconds':round(time.monotonic()-started,2)}),flush=True)


if __name__ == '__main__':
    main()
