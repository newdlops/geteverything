"""Repair early automatic identities while preserving raw price observations and manual work."""
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from gadmin.deals.models import ClassificationState,DealMeasurements,DealProduct,Product,ProductPrice
from . import jobs
from .identity import MULTI_PRODUCT, clean_title


def repair_unsafe(limit=200):
    """Detach mixed offers only; existing product UUIDs and raw prices remain intact."""
    affected=[]
    candidates=DealProduct.objects.filter(status='ready',manual_override=False,source='llm').order_by('-deal_id')[:max(1,min(limit,2000))]
    for candidate in candidates:
        if not MULTI_PRODUCT.search(clean_title(candidate.input_title)):continue
        with transaction.atomic():
            row=DealProduct.objects.select_for_update().filter(pk=candidate.pk,manual_override=False,
                request_revision=candidate.request_revision,status='ready').first()
            if row is None:continue
            affected.append({'deal_id':row.pk,'product_id':str(row.product_id)})
            row.product=None;row.status='review';row.source='';row.last_error='not_a_single_product'
            row.request_revision+=1;row.lease_until=None;row.save()
            ProductPrice.objects.filter(deal_id=row.pk,identity_revision=row.identity_revision).update(product=None)
    result={'at':timezone.now().isoformat(),'unlinked_mixed_offers':affected}
    ClassificationState.objects.update_or_create(key='products:repair_unsafe',defaults={'value':result})
    return result


def repair(limit=200):
    audit=[];products=set()
    waiting=DealProduct.objects.filter(status='review',manual_override=False,last_error='awaiting_model_capacity').update(status='pending')
    for _ in range(limit):
        with transaction.atomic():
            row=(DealProduct.objects.select_for_update(skip_locked=True).filter(status='ready',manual_override=False)
                 .exclude(processor_version=jobs.VERSION).order_by('deal_id').first())
            if row is None:break
            audit.append({'deal_id':row.pk,'product_id':str(row.product_id),'extraction':row.extraction,'source':row.source,
                          'processor_version':row.processor_version,'identity_revision':row.identity_revision})
            if row.product_id:products.add(row.product_id)
            row.request_revision+=1;row.product=None;row.status='pending';row.source='';row.extraction={}
            row.lease_until=None;row.last_error='';row.attempts=0;row.next_attempt_at=timezone.now()
            row.save()
            ProductPrice.objects.filter(deal_id=row.pk,identity_revision=row.identity_revision).update(product=None,processed_at=None)
            if 'gx' in row.input_title.lower():
                DealMeasurements.objects.filter(deal_id=row.pk).update(status='pending',lease_until=None,request_revision=F('request_revision')+1)
        jobs.process_rule(row)
    # These UUIDs were created by the initial automatic pass. Never remove referenced/manual products.
    empty=Product.objects.filter(pk__in=products,verified=False,assignments__isnull=True,prices__isnull=True,productmatchexample__isnull=True)
    removed=list(empty.values('id','name','identity_key','attributes'))
    empty.delete()
    jobs.process_prices(limit)
    report={'at':timezone.now().isoformat(),'waiting_relabelled':waiting,'reprocessed':len(audit),'audit':audit,
            'removed_unreferenced_generated_products':[{**row,'id':str(row['id'])} for row in removed]}
    ClassificationState.objects.update_or_create(key='products:repair',defaults={'value':{key:value for key,value in report.items() if key!='audit'}})
    return report
