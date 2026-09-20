"""A separate durable queue so manual category decisions never freeze prices."""
from datetime import timedelta
import time
from .parser import analyze, VERSION

INPUT_FIELDS = ('subject','price','currency','delivery_price','numeric_evidence')


def snapshot(deal):
    return {field:(getattr(deal,field) or ({} if field=='numeric_evidence' else '')) if field in ('subject','numeric_evidence') else getattr(deal,field) for field in INPUT_FIELDS}


def process_batch(limit=25):
    from django.db import transaction
    from django.db.models import Q
    from django.utils import timezone
    from gadmin.deals.models import DealMeasurements
    processed = 0
    for _ in range(limit):
        now = timezone.now()
        with transaction.atomic():
            job = (DealMeasurements.objects.select_for_update(skip_locked=True).filter(status='pending')
                   .filter(Q(lease_until__isnull=True)|Q(lease_until__lt=now)).order_by('priority','-deal_id').first())
            if job is None:
                break
            job.lease_until = now+timedelta(seconds=120)
            job.save(update_fields=['lease_until'])
        try:
            result = analyze(job.input)
            values = {'result':result,'status':result['status'],'last_error':''}
        except (ValueError,TypeError,ArithmeticError,KeyError) as exc:
            values = {'result':{},'status':'error','last_error':type(exc).__name__}
        DealMeasurements.objects.filter(pk=job.pk,request_revision=job.request_revision).update(
            **values,parser_version=VERSION,processed_at=timezone.now(),lease_until=None)
        processed += 1
    return processed


def backfill(limit=100):
    from django.db import transaction
    from gadmin.deals.models import ClassificationState,Deal,DealMeasurements
    if DealMeasurements.objects.filter(status='pending',priority=10).count()>=200:
        return
    with transaction.atomic():
        state,_ = ClassificationState.objects.select_for_update().get_or_create(key='measurements-backfill',defaults={'value':{
            'cursor':(Deal.objects.order_by('-id').values_list('id',flat=True).first() or 0)+1,'scanned':0,'phase':'scanning'}})
        value = state.value
        if value['phase']=='queued' and not DealMeasurements.objects.filter(status='pending',priority=10).exists():
            value.update(phase='complete',completed_at=time.time())
        if value['phase']=='scanning':
            deals = list(Deal.objects.select_for_update().filter(id__lt=value['cursor']).order_by('-id').only('id',*INPUT_FIELDS)[:limit])
            DealMeasurements.objects.bulk_create([DealMeasurements(deal=deal,input=snapshot(deal),priority=10) for deal in deals],ignore_conflicts=True)
            if deals:
                value.update(cursor=deals[-1].pk,scanned=value['scanned']+len(deals))
            else:
                value['phase']='queued'
        state.value = value
        state.save(update_fields=['value'])
