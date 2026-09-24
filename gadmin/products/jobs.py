"""Product extraction shares the existing local model and a bounded durable queue."""
from datetime import timedelta
import hashlib
import json
import time

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from gadmin.categories.llm import InvalidResult, Unavailable
from gadmin.deals.models import (ClassificationState, Deal, DealClassification, DealProduct,
                                 Product, ProductMatchExample, ProductPrice)
from gadmin.metrics.jobs import snapshot
from gadmin.metrics.parser import analyze
from . import catalog, identity, learning, local_model

VERSION = identity.VERSION + '/' + local_model.PROMPT_VERSION
MODEL_QUEUE_LIMIT = 40


def seed(deal, historical=False):
    """Caller holds the Deal row lock, matching the crawler trigger's lock order."""
    job, _ = DealProduct.objects.get_or_create(deal=deal, defaults={
        'input_title':deal.subject or '', 'priority':10 if historical else 0})
    from .sources import seed as seed_source
    seed_source(deal)
    ProductPrice.objects.get_or_create(deal=deal, price_revision=job.price_revision, defaults={
        'identity_revision':job.identity_revision, 'product_id':job.product_id if job.status=='ready' else None,
        'published_at':deal.write_at or deal.create_at or timezone.now(),
        'is_backfill':historical, 'input':snapshot(deal)})
    return job


def backfill(limit=50):
    if DealProduct.objects.filter(status='pending',priority=10).exclude(last_error='awaiting_model_capacity').count()>=100:
        return
    with transaction.atomic():
        state,_=ClassificationState.objects.select_for_update().get_or_create(key='products:backfill',defaults={'value':{
            'cursor':(Deal.objects.order_by('-id').values_list('id',flat=True).first() or 0)+1,'scanned':0,'phase':'scanning'}})
        value=dict(state.value)
        if value['phase']=='scanning':
            rows=list(Deal.objects.select_for_update().filter(id__lt=value['cursor']).order_by('-id').only(
                'id','write_at','create_at','subject','price','currency','delivery_price','numeric_evidence','shop_url_1','shop_url_2')[:limit])
            for deal in rows:seed(deal,historical=True)
            if rows:value.update(cursor=rows[-1].pk,scanned=value['scanned']+len(rows))
            else:value.update(phase='snapshots_queued',scanned_at=time.time())
        if value['phase']=='snapshots_queued' and not ProductPrice.objects.filter(processed_at=None).exists():
            value.update(phase='snapshots_complete',completed_at=time.time())
        state.value=value
        state.save(update_fields=['value'])


def refill_model_queue():
    available=max(0,MODEL_QUEUE_LIMIT-DealProduct.objects.filter(status='llm').count())
    if not available:return
    with transaction.atomic():
        ids=list(DealProduct.objects.select_for_update(skip_locked=True).filter(status__in=['pending','review'],
            last_error='awaiting_model_capacity',manual_override=False).order_by('priority','-deal_id').values_list('deal_id',flat=True)[:available])
        DealProduct.objects.filter(pk__in=ids).update(status='llm',last_error='',next_attempt_at=timezone.now())


def claim(stage):
    now=timezone.now()
    with transaction.atomic():
        job=(DealProduct.objects.select_for_update(skip_locked=True).filter(status=stage,manual_override=False,next_attempt_at__lte=now)
             .exclude(last_error='awaiting_model_capacity')
             .filter(Q(lease_until=None)|Q(lease_until__lt=now)).order_by('priority','-deal_id').first())
        if job:
            job.lease_until=now+timedelta(seconds=300)
            job.save(update_fields=['lease_until'])
        return job


def finish(job, **values):
    return DealProduct.objects.filter(pk=job.pk,request_revision=job.request_revision,input_title=job.input_title,
        manual_override=False).update(lease_until=None,**values)


def reviewed_alias(title):
    key=identity.alias_title(title)
    rows=list(ProductMatchExample.objects.filter(same_product=True,product__isnull=False,product__is_active=True,
        extraction__alias=key).select_related('product')[:3])
    ids={row.product_id for row in rows}
    if len(ids)==1 and rows[0].product.attributes==identity.canonical_data({
            'model':rows[0].product.model,'attributes':identity.facts(title)})['attributes']:
        return rows[0].product
    return None


def candidate_products(title, data):
    query=Product.objects.filter(is_active=True)
    if data.get('brand'):query=query.filter(brand__iexact=data['brand'])
    elif data.get('model'):query=query.filter(model__iexact=data['model'])
    else:return []
    state=ClassificationState.objects.filter(key='products:matcher').values_list('value',flat=True).first() or {}
    weights=state.get('weights')
    if not weights:return []
    rows=[]
    for product in query.order_by('-verified','-updated_at')[:30]:
        target=product_title(product)
        score=learning.probability(weights,learning.features(title,target))
        rows.append({'id':str(product.pk),'name':target,'score':round(score,4),
                     'specs_match':product.attributes==data.get('attributes'),'model_version':state['version']})
    return sorted(rows,key=lambda row:row['score'],reverse=True)[:5]


def product_title(product):
    sizes=[]
    from decimal import Decimal
    for size in product.attributes.get('sizes',[]):
        kind,_,number=size.partition(':')
        sizes.append(format(Decimal(number),'f')+('g' if kind=='weight_g' else 'ml'))
    return ' '.join(filter(None,[product.name,product.model,*sizes,*product.attributes.get('specs',[])]))[:512]


def cached_product(title):
    query=DealProduct.objects.filter(input_hash=identity.cache_hash(title),processor_version=VERSION,
        status='ready',manual_override=False,product__is_active=True,extraction__attributes=identity.facts(title))
    # Conflicting model extractions are not a reusable identity, even when their
    # cleaned title and physical specifications happen to match.
    ids=list(query.order_by().values_list('product_id',flat=True).distinct()[:2])
    if len(ids)!=1:return None
    return query.select_related('product').order_by('deal_id').first()


def resolve(job, data, source, target=None, candidates=None):
    if identity.offer_issue(job.input_title):return reject_offer(job)
    data=identity.canonical_data(data)
    with transaction.atomic():
        catalog.lock()
        current=DealProduct.objects.select_for_update().filter(pk=job.pk,request_revision=job.request_revision,
            input_title=job.input_title,manual_override=False).first()
        if not current:return 0
        from . import sources
        if source == 'identifier':
            matched = sources.match(current, data)
            if not matched:
                return 0
            target, data = matched
        elif source != 'learned' and target is None:
            matched = sources.match(current, data)
            if matched:
                target, data = matched
                source = 'identifier'
        # A merchant ID is useful evidence, but it cannot override conflicting
        # container facts already present in the destination history.
        if target:
            candidate=catalog.canonical(Product.objects.get(pk=target.pk))
            if catalog.has_container_conflict(candidate,data):target=None
        category=DealClassification.objects.filter(deal_id=job.pk,status='ready').values_list('category',flat=True).first() or data.get('category','')
        # Cached automatic links must reconsider missing packaging if the catalog
        # now has more than one explicit format. Reviewed aliases remain binding.
        if target and source not in {'learned', 'identifier'} and identity.container_keys(data):target=None
        product=catalog.canonical(Product.objects.get(pk=target.pk)) if target else None
        if product and not product.is_active:return 0
        if product is None:
            product=catalog.automatic(data,category)
        current.product=product
        current.extraction=data
        current.candidates=candidates or []
        current.status='ready';current.source=source;current.last_error='';current.lease_until=None
        current.processed_at=timezone.now();current.input_hash=identity.cache_hash(job.input_title)
        current.processor_version=VERSION
        current.save()
        ProductPrice.objects.filter(deal_id=job.pk,identity_revision=current.identity_revision).update(product=product)
    # Release the assignment lock first: the crawler's classification trigger runs before products.
    classifications=DealClassification.objects.filter(deal_id=job.pk,input_title=job.input_title,
        manual_override=False,category='',deal__product_assignment__product_id=product.pk,
        deal__product_assignment__request_revision=job.request_revision,deal__product_assignment__status='ready')
    if product.verified and product.category:
        classifications.update(category=product.category,status='ready',source='rule',candidate='',
            reason='verified_product',classified_at=timezone.now(),request_revision=F('request_revision')+1,lease_until=None)
    elif data.get('category'):classifications.update(candidate=data['category'])
    return 1


def reject_offer(job):
    with transaction.atomic():
        catalog.lock()
        current=DealProduct.objects.select_for_update().filter(pk=job.pk,request_revision=job.request_revision,
            input_title=job.input_title,manual_override=False).first()
        if not current:return 0
        ProductPrice.objects.filter(deal_id=current.pk,identity_revision=current.identity_revision).update(product=None)
        return finish(job,product=None,status='review',last_error='not_a_single_product',processor_version=VERSION)


def process_rule(job):
    title=identity.clean_title(job.input_title)
    if len(identity.compact(title))<3:
        return finish(job,status='review',last_error='unavailable_title')
    if identity.offer_issue(job.input_title):
        return reject_offer(job)
    target=reviewed_alias(job.input_title)
    if target:
        data={'brand':target.brand,'name':target.name,'model':target.model,'variant':'','attributes':target.attributes,'category':target.category}
        return resolve(job,data,'learned',target=target)
    from .sources import try_link
    if try_link(job.pk):return 1
    data=identity.extract_rule(job.input_title)
    if data:return resolve(job,data,'rule')
    cached=cached_product(job.input_title)
    if cached:
        return resolve(job,cached.extraction,cached.source,target=cached.product)
    waiting=DealProduct.objects.filter(status='llm').count()>=MODEL_QUEUE_LIMIT
    return finish(job,status='pending' if waiting else 'llm',last_error='awaiting_model_capacity' if waiting else '',
                  input_hash=identity.cache_hash(job.input_title),processor_version=VERSION,
                  extraction={'attributes':identity.facts(job.input_title)})


def process_rules(limit=20):
    count=0
    for _ in range(limit):
        job=claim('pending')
        if job is None:break
        try:process_rule(job)
        except (ValueError,TypeError,KeyError) as exc:finish(job,status='error',last_error='rule_'+type(exc).__name__)
        count+=1
    return count


def record_model(outcome):
    with transaction.atomic():
        state,_=ClassificationState.objects.select_for_update().get_or_create(key='products:model',defaults={'value':{}})
        value=dict(state.value);value[outcome]=int(value.get(outcome,0))+1;value['last_at']=time.time()
        value['prompt_version']=local_model.PROMPT_VERSION
        state.value=value;state.save(update_fields=['value'])


def process_llm(job, model):
    if identity.offer_issue(job.input_title):
        return reject_offer(job)
    target=reviewed_alias(job.input_title)
    if target:
        data={'brand':target.brand,'name':target.name,'model':target.model,'variant':'','attributes':target.attributes,'category':target.category}
        return resolve(job,data,'learned',target=target)
    from .sources import try_link
    if try_link(job.pk):return 1
    cached=cached_product(job.input_title)
    if cached:
        result=resolve(job,cached.extraction,cached.source,target=cached.product)
        if result:record_model('cache_hits')
        return result
    examples=list(ProductMatchExample.objects.filter(same_product=True).exclude(extraction={}).order_by('-id').values_list('extraction',flat=True)[:2])
    # Examples are explicitly confirmed inputs/outputs; aliases and audit fields stay outside the prompt.
    examples=[row['llm_example'] for row in examples if 'llm_example' in row]
    try:
        data,reason,raw=local_model.extract(model,job.input_title,examples)
    except Unavailable:
        return finish(job,next_attempt_at=timezone.now()+timedelta(seconds=60),last_error='model_unavailable')
    except InvalidResult as exc:
        attempts=job.attempts+1
        record_model('invalid')
        return finish(job,status='error' if attempts>=3 else 'llm',attempts=attempts,last_error=str(exc)[:160],
            next_attempt_at=timezone.now()+timedelta(seconds=60*attempts))
    if data:
        target=reviewed_alias(job.input_title)
        result=resolve(job,data,'learned' if target else 'llm',target=target,candidates=candidate_products(job.input_title,data))
        if result:record_model('linked')
        return result
    result=finish(job,status='review',extraction={'raw':raw},last_error=reason,processed_at=timezone.now(),processor_version=VERSION)
    if result:record_model('abstained')
    return result


def process_prices(limit=30):
    count=0
    for _ in range(limit):
        with transaction.atomic():
            row=ProductPrice.objects.select_for_update(skip_locked=True).filter(processed_at=None).order_by('-id').first()
            if row is None:break
            try:row.result=analyze(row.input)
            except (ValueError,TypeError,ArithmeticError,KeyError) as exc:row.result={'status':'error','error':type(exc).__name__}
            row.processed_at=timezone.now()
            row.save(update_fields=['result','processed_at'])
            count+=1
    return count


def add_example(left, right, same, product=None, extraction=None, origin='operator', actor=''):
    key=hashlib.sha256(json.dumps([identity.normalize(left),identity.normalize(right)],ensure_ascii=False).encode()).hexdigest()
    upsert=ProductMatchExample.objects.get_or_create if origin=='bootstrap_review' else ProductMatchExample.objects.update_or_create
    row,_=upsert(example_key=key,defaults={
        'left_title':left[:512],'right_title':right[:512],'same_product':same,'product':product,
        'extraction':extraction or {},'origin':origin,'actor':actor[:150]})
    return row


def manual_assign(deal_id, product, actor, expected_revision, llm_target=None, extraction_reviewed=None):
    with transaction.atomic():
        catalog.lock()
        if product:
            product=catalog.canonical(Product.objects.get(pk=product.pk))
            if not product.is_active:raise ValueError('현재 목록의 상품을 선택하세요.')
        current=DealProduct.objects.select_for_update().get(pk=deal_id)
        if current.request_revision!=expected_revision:raise ValueError('게시물 제목 또는 연결이 바뀌었습니다. 새로고침 후 다시 확인하세요.')
        if llm_target is not None:
            from .sft import valid_target
            if not product or not valid_target(current.input_title,llm_target):
                raise ValueError('제목 근거가 검증된 상품 추출 정답만 저장할 수 있습니다.')
        previous=current.product
        current.product=product;current.manual_override=True;current.source='manual'
        current.status='ready' if product else 'review';current.lease_until=None
        current.last_error='operator_override';current.request_revision+=1;current.processed_at=timezone.now()
        if llm_target is not None:
            current.extraction={**current.extraction,**{key:llm_target.get(key,'') for key in ('brand','name','model','variant')},
                'category':llm_target.get('category',''),'attributes':identity.facts(current.input_title)}
        current.save()
        ProductPrice.objects.filter(deal_id=deal_id,identity_revision=current.identity_revision).update(product=product)
        if previous and previous!=product:
            add_example(current.input_title,product_title(previous),False,previous,actor=actor)
        if product:
            confirmed={'alias':identity.alias_title(current.input_title)}
            from .sft import FIELDS, valid_target
            candidate={key:current.extraction.get(key,'') for key in FIELDS}
            candidate['is_product']=True
            candidate['category']=(product.category or 'unknown').split('.')[0]
            if (extraction_reviewed is not False and previous==product and current.extraction.get('attributes')==product.attributes and
                    identity.signature(current.extraction)==product.identity_key and
                    valid_target(current.input_title,candidate)):
                confirmed['llm_target']=candidate
                confirmed['llm_example']={'title':current.input_title,'output':candidate}
            if llm_target is not None:
                confirmed['llm_target']=dict(llm_target)
                confirmed['llm_example']={'title':current.input_title,'output':dict(llm_target)}
            add_example(current.input_title,product_title(product),True,product,
                extraction=confirmed if 'llm_target' in confirmed else {'alias':confirmed['alias']},actor=actor)
        return current


def train_if_changed():
    count=ProductMatchExample.objects.count()
    state=ClassificationState.objects.filter(key='products:training').values_list('value',flat=True).first() or {}
    # Small retraining runs no more than once per hour, including failed/insufficient-data runs.
    if time.time()-state.get('at',0)<3600:return
    try:result={'status':'ready','version':learning.train_stored()}
    except ValueError as exc:result={'status':'waiting_for_examples','reason':str(exc)}
    ClassificationState.objects.update_or_create(key='products:training',defaults={'value':{'at':time.time(),'examples':count,**result}})
