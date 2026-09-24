"""Repair automatic identities without deleting UUIDs or price observations.

Every historical price is interpreted using its own title. A current assignment
must never relabel older revisions after a title changed to a different product.
"""
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import uuid

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone

from gadmin.deals.models import DealProduct, Product, ProductMatchExample, ProductPrice
from . import catalog, identity


def encoded(value):
    return json.dumps(value, cls=DjangoJSONEncoder, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def price_digest(rows):
    return hashlib.sha256(encoded([{key:value for key,value in row.items() if key!='product_id'}
                                  for row in rows]).encode()).hexdigest()


def interpretation(title, extraction=None):
    if identity.offer_issue(title):return None, 'not_a_single_product'
    data=identity.extract_rule(title)
    if data:return data, ''
    if extraction and extraction.get('name'):
        data,_=identity.grounded(title, {**extraction, 'is_product':True})
        if data:return data, ''
    return None, 'unchanged'


def reference_title(ref):
    row=ref['row']
    return row['input_title'] if ref['kind']=='job' else (row['input'] or {}).get('subject','')


def deduplicate(*, apply=False, backup=None, product_ids=None):
    if apply and not backup:raise ValueError('Applying a repair requires an exclusive backup path.')
    from .jobs import VERSION
    with transaction.atomic():
        catalog.lock()
        scoped_ids={uuid.UUID(str(pk)) for pk in product_ids} if product_ids is not None else None
        product_keys=dict(Product.objects.values_list('identity_key','pk'))
        active_keys=set(Product.objects.filter(is_active=True).values_list('identity_key',flat=True))
        selected_products=Product.objects.filter(pk__in=scoped_ids) if scoped_ids is not None else Product.objects.all()
        products={row.pk:row for row in selected_products}
        missing=scoped_ids-set(products) if scoped_ids is not None else set()
        if missing:raise ValueError('Unknown product id in repair scope.')
        active_before=Product.objects.filter(is_active=True).count()
        protected=set(Product.objects.filter(verified=True).values_list('pk',flat=True))
        protected.update(DealProduct.objects.filter(manual_override=True).values_list('product_id',flat=True))
        protected.update(ProductPrice.objects.filter(deal__product_assignment__manual_override=True).values_list('product_id',flat=True))
        protected.update(ProductMatchExample.objects.exclude(product=None).values_list('product_id',flat=True))
        eligible={pk for pk,row in products.items() if row.is_active and pk not in protected
                  and (scoped_ids is None or pk in scoped_ids)}
        # All writers take the catalog lock before assignments. The crawler takes
        # assignment then price locks and never needs the catalog lock.
        affected_deals=set(DealProduct.objects.filter(product_id__in=eligible).values_list('pk',flat=True))
        affected_deals.update(ProductPrice.objects.filter(product_id__in=eligible).values_list('deal_id',flat=True))
        job_rows=list(DealProduct.objects.select_for_update().filter(pk__in=affected_deals).order_by('pk').values())
        product_rows=list(Product.objects.select_for_update().filter(pk__in=eligible).order_by('pk').values())
        price_rows=list(ProductPrice.objects.select_for_update().filter(product_id__in=eligible).order_by('pk').values())
        jobs={row['deal_id']:row for row in job_rows}
        references=[]
        preserve=set()
        for row in job_rows:
            if row['product_id'] not in eligible:continue
            data,reason=interpretation(row['input_title'],row['extraction'])
            references.append({'kind':'job','row':row,'data':data,'reason':reason,'product':row['product_id']})
            if reason=='unchanged':preserve.add(row['product_id'])
        for row in price_rows:
            job=jobs.get(row['deal_id'],{})
            title=row['input'].get('subject','')
            extraction=job.get('extraction') if job.get('input_title')==title else None
            data,reason=interpretation(title,extraction)
            references.append({'kind':'price','row':row,'data':data,'reason':reason,'product':row['product_id']})
            if reason=='unchanged':preserve.add(row['product_id'])
        owners=product_keys
        observed={identity.signature(ref['data']) for ref in references if ref['data']}
        observed.update(active_keys)
        for ref in references:
            data=ref['data']
            ref['group_data']=data
            if not data or data['attributes'].get('container'):continue
            keys=identity.container_keys(data)
            known=[kind for kind,key in keys.items() if kind and key in observed]
            if len(known)==1:ref['group_data']=identity.with_container(data,known[0])
        # The same normalized title can be split when the extractor partitions
        # its words differently between brand/name/variant. Only collapse those
        # outputs when the entire title alias and every title-grounded identity
        # fact agree; title aliases retain model, flavor, size, and packaging.
        aliases=defaultdict(list)
        for ref in references:
            if ref['data']:
                aliases[identity.cache_hash(reference_title(ref))].append(ref)
        for group in aliases.values():
            signatures={identity.signature(ref['group_data']) for ref in group}
            if len(signatures)<2 or any(identity.offer_issue(reference_title(ref)) for ref in group):continue
            title_facts={encoded(identity.facts(reference_title(ref))) for ref in group}
            if len(title_facts)!=1:continue
            if any(identity.canonical_data(ref['data']).get('attributes',{}) != identity.facts(reference_title(ref))
                   for ref in group):continue
            by_signature=defaultdict(set)
            for ref in group:by_signature[identity.signature(ref['group_data'])].add(ref['row']['deal_id'])
            winner=min(signatures,key=lambda key:(-len(by_signature[key]),key))
            representative=next(ref['group_data'] for ref in group if identity.signature(ref['group_data'])==winner)
            for ref in group:
                ref['group_data']=representative
                ref['alias_data']=representative
        # Never rewrite an operator decision, including a protected owner of the
        # destination key. Preserve an entire source if any title is ambiguous.
        while True:
            blocked={identity.signature(ref['group_data']) for ref in references if ref['data'] and
                     (ref['product'] in preserve or (identity.signature(ref['group_data']) in owners and
                      owners[identity.signature(ref['group_data'])] not in eligible))}
            previous=set(preserve)
            preserve.update(ref['product'] for ref in references if ref['data'] and identity.signature(ref['group_data']) in blocked)
            if preserve==previous:break
        refs=[ref for ref in references if ref['product'] not in preserve]
        groups=defaultdict(list)
        for ref in refs:
            if ref['data']:groups[identity.signature(ref['group_data'])].append(ref)
        updates={}
        targets={}
        used=set()
        previous_keys={pk:identity.signature({'brand':row.brand,'name':row.name,'model':row.model,
                       'attributes':row.attributes}) for pk,row in products.items() if identity.KNOWN_MODEL.fullmatch(row.model)}
        ordered_groups=sorted(groups.items(),key=lambda pair:(
            not any(products[ref['product']].identity_key==pair[0] for ref in pair[1]),
            not any(previous_keys.get(ref['product'])==pair[0] for ref in pair[1]),pair[0]))
        for key,group in ordered_groups:
            members={ref['product'] for ref in group}
            ordered=sorted(members-used,key=lambda pk:(products[pk].identity_key!=key,previous_keys.get(pk)!=key,
                           products[pk].created_at,str(pk)))
            winner=ordered[0] if ordered else uuid.uuid4()
            data=identity.canonical_data(group[0]['group_data'])
            targets[key]=winner
            used.add(winner)
            previous=products.get(winner)
            updates[winner]={'identity_key':key,'name':identity.display_name(data),'brand':data.get('brand',''),
                'model':data.get('model',''),'attributes':data['attributes'],
                'category':previous.category if previous else data.get('category',''),
                'is_active':True,'merged_into_id':None}
        destinations=defaultdict(set)
        job_updates={}
        price_updates={}
        for ref in refs:
            row=ref['row']
            target=targets[identity.signature(ref['group_data'])] if ref['data'] else None
            if target:destinations[ref['product']].add(target)
            if ref['kind']=='price':
                if row['product_id']!=target:price_updates[row['id']]=target
                continue
            fields={'product_id':target,'status':'ready' if target else 'review',
                    'processor_version':VERSION,'last_error':'' if target else ref['reason']}
            if target:
                fields['extraction']=identity.canonical_data(ref.get('alias_data') or ref['data'])
                fields['input_hash']=identity.cache_hash(row['input_title'])
            if any(row.get(key)!=value for key,value in fields.items()):
                job_updates[row['deal_id']]={**fields,'request_revision':row['request_revision']+1,
                    'lease_until':None,'candidates':[],'processed_at':timezone.now()}
        for pk in eligible-preserve-used:
            destination=destinations[pk]
            updates[pk]={'is_active':False,'merged_into_id':next(iter(destination)) if len(destination)==1 else None,
                         'identity_key':hashlib.sha256(('archived-product:'+str(pk)).encode()).hexdigest()}
        updates={pk:values for pk,values in updates.items() if pk not in products or
                 any(getattr(products[pk],key)!=value for key,value in values.items())}
        summary={'applied':apply,'active_before':active_before,
                 'active_after':active_before+
                    sum(int(values['is_active'])-int(products[pk].is_active if pk in products else False) for pk,values in updates.items()),
                 'merged':sum(bool(row.get('merged_into_id')) for row in updates.values()),
                 'archived_invalid':sum(not row['is_active'] and not row.get('merged_into_id') for row in updates.values()),
                 'products_updated':len(updates),'products_created':sum(pk not in products for pk in updates),
                 'assignments_updated':len(job_updates),'assignments_detached':sum(not row['product_id'] for row in job_updates.values()),
                 'prices_moved':sum(bool(target) for target in price_updates.values()),
                 'prices_detached':sum(not target for target in price_updates.values()),
                 'prices_checked':len(price_rows),'price_payload_sha256':price_digest(price_rows),
                 'protected_products':len(protected-{None}),'preserved_ambiguous':len(preserve),
                 'scope_product_ids':sorted(map(str,scoped_ids)) if scoped_ids is not None else None,
                 'merged_ids':[[str(pk),str(values['merged_into_id'])] for pk,values in updates.items()
                               if values.get('merged_into_id')],
                 'created_ids':[str(pk) for pk in updates if pk not in products]}
        if not apply:return summary
        path=Path(backup)
        with path.open('x',encoding='utf-8') as handle:
            path.chmod(0o600)
            handle.write(encoded({'version':identity.VERSION,'summary':summary,'products':product_rows,
                'assignments':job_rows,'prices':price_rows,'plan':{
                    'products':{str(pk):value for pk,value in updates.items()},
                    'assignments':job_updates,'prices':price_updates}}))
            handle.flush();os.fsync(handle.fileno())
        # Release old unique keys before setting the canonical keys. UUIDs stay.
        for pk,values in updates.items():
            if pk in products and values.get('identity_key')!=products[pk].identity_key:
                Product.objects.filter(pk=pk).update(identity_key=hashlib.sha256(('repair-product:'+str(pk)).encode()).hexdigest())
        for pk,values in updates.items():
            if pk in products:Product.objects.filter(pk=pk).update(**values,updated_at=timezone.now())
            else:Product.objects.create(pk=pk,**values)
        for pk,values in job_updates.items():DealProduct.objects.filter(pk=pk).update(**values)
        for pk,target in price_updates.items():ProductPrice.objects.filter(pk=pk).update(product_id=target)
        after=list(ProductPrice.objects.filter(pk__in=[row['id'] for row in price_rows]).order_by('pk').values())
        if price_digest(after)!=summary['price_payload_sha256']:raise RuntimeError('Price payload changed; repair rolled back.')
        summary['backup']=str(path)
        summary['price_payload_preserved']=True
    return summary
