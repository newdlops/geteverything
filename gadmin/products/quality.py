"""Product identity drift checks and bounded review snapshots.

The audit only reads product links. Recording its metrics never creates training
labels or merges products: a numeric token can be a real model option, and
matching names do not prove matching SKUs.
"""
from collections import Counter, defaultdict
import json
import re
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from gadmin.metrics.parser import quantities
from . import identity


REPLY_COUNT = re.compile(r'\s+\[(\d{1,3})\]\s*$')
PROMOTION = re.compile(r'네멤|티멤|무료배송|카드할인|역대가|단하루특가|\[[^]]*\d+[^]]*\]')
STORE_BRANDS = {identity.compact(value) for value in identity.SHOP_TAGS}
FLAVORS = {'lime','lemon','cherry','vanilla','mango','peach','grape','yuzu','original'}
COLORS = {'black','white','silver','blue','red','pink'}
TREND_KEYS = ('active_products', 'ready_assignments', 'reply_count_as_identity_option',
              'numeric_split_review_groups', 'same_signature_review_groups',
              'cross_post_conflict_products', 'shop_brand_products', 'promotion_name_products')


def _base_key(product):
    """Only ignore numeric options when proposing a review, never for linking."""
    attributes = product.get('attributes') or {}
    brand = identity.normalize(product.get('brand'))
    return (identity.BRANDS.get(brand, identity.compact(brand)),
            identity.compact(product.get('name')), identity.compact(product.get('model')),
            json.dumps({key:value for key,value in attributes.items() if key != 'numeric_options'},
                       sort_keys=True, ensure_ascii=False, separators=(',', ':')))


def summarize(products, assignments, *, example_limit=12):
    products = list(products)
    by_id = {product['id']: product for product in products}
    links = Counter()
    contaminated = Counter()
    pack_counts = defaultdict(set)
    observations = defaultdict(dict)
    for row in assignments:
        product_id = row.get('product_id')
        if product_id not in by_id:
            continue
        links[product_id] += 1
        title = row.get('input_title') or ''
        extraction = row.get('extraction') or {}
        attributes = extraction.get('attributes') or {}
        # Compare independently parsed title evidence: saved extractions can
        # repeat the same mistaken fields across several linked posts.
        title_facts = identity.facts(title)
        match = REPLY_COUNT.search(identity.normalize(title))
        numeric_options = attributes.get('numeric_options')
        if match and isinstance(numeric_options,list) and match[1] in numeric_options:
            contaminated[product_id] += 1
        quantity = quantities(identity.clean_title(title)).get('quantity')
        if quantity:
            pack_counts[product_id].add((quantity['count'], quantity['unit']))
        observed = observations[product_id]
        brand = identity.normalize(extraction.get('brand'))
        if brand:
            observed.setdefault('brand',set()).add(identity.BRANDS.get(brand, identity.compact(brand)))
        model = identity.compact(extraction.get('model'))
        if model:
            observed.setdefault('model',set()).add(model)
        sizes = title_facts.get('sizes') or []
        if isinstance(sizes,list) and len(sizes)==1:
            observed.setdefault('size',set()).add(sizes[0])
        container = title_facts.get('container')
        if container:
            observed.setdefault('container',set()).add(container)
        options = set(title_facts.get('options') or [])
        for kind,choices in (('flavor',FLAVORS),('color',COLORS)):
            selected=options & choices
            if len(selected)==1:
                observed.setdefault(kind,set()).update(selected)

    groups = defaultdict(list)
    signatures = defaultdict(list)
    for product in products:
        groups[_base_key(product)].append(product)
        signatures[identity.signature({'brand':product.get('brand',''), 'name':product.get('name',''),
            'model':product.get('model',''), 'attributes':product.get('attributes') or {}})].append(product)

    splits = [rows for rows in groups.values() if len(rows)>1 and any(contaminated[row['id']] for row in rows)]
    duplicates = [rows for rows in signatures.values() if len(rows)>1]
    shop_brands = [product for product in products if identity.compact(product.get('brand')) in STORE_BRANDS]
    promo_names = [product for product in products if PROMOTION.search(product.get('name') or '')]
    conflicts={kind:[] for kind in ('brand','model','size','container','flavor','color')}
    for product_id,observed in observations.items():
        for kind in conflicts:
            if len(observed.get(kind,()))>1:
                conflicts[kind].append(product_id)
    conflict_ids={product_id for rows in conflicts.values() for product_id in rows}
    conflict_examples=[{'product_id':str(product_id),'name':by_id[product_id].get('name',''),
                        'linked_posts':links[product_id],
                        'conflicts':{kind:sorted(observations[product_id][kind]) for kind in conflicts
                                     if len(observations[product_id].get(kind,()))>1}}
                       for product_id in sorted(conflict_ids,key=lambda pk:(-links[pk],str(pk)))[:max(0,example_limit)]]
    ranked = sorted(splits, key=lambda rows:(-sum(links[row['id']] for row in rows), str(rows[0]['id'])))
    examples = [{'name':rows[0].get('name',''), 'product_ids':[str(row['id']) for row in rows],
                 'linked_posts':sum(links[row['id']] for row in rows),
                 'reply_count_posts':sum(contaminated[row['id']] for row in rows)}
                for rows in ranked[:max(0, example_limit)]]
    return {
        'version':identity.VERSION,
        'active_products':len(products), 'ready_assignments':sum(links.values()),
        'reply_count_as_identity_option':sum(contaminated.values()),
        'reply_count_product_ids':len(contaminated),
        'numeric_split_review_groups':len(splits),
        'numeric_split_review_products':sum(len(rows) for rows in splits),
        'numeric_split_review_assignments':sum(links[row['id']] for rows in splits for row in rows),
        'same_signature_review_groups':len(duplicates),
        'same_signature_review_products':sum(len(rows) for rows in duplicates),
        'shop_brand_products':len(shop_brands), 'promotion_name_products':len(promo_names),
        'products_with_multiple_pack_counts':sum(len(counts)>1 for counts in pack_counts.values()),
        'cross_post_conflicts':{kind:len(rows) for kind,rows in conflicts.items()},
        'cross_post_conflict_products':len(conflict_ids),
        'review_candidates':examples,
        'conflict_candidates':conflict_examples,
    }


def audit(*, example_limit=12):
    from gadmin.deals.models import DealProduct, Product
    products=Product.objects.filter(is_active=True).values('id','name','brand','model','attributes').iterator(chunk_size=500)
    assignments=DealProduct.objects.filter(status='ready',product__isnull=False).values(
        'product_id','input_title','extraction').iterator(chunk_size=500)
    return summarize(products, assignments, example_limit=example_limit)


def record(summary, *, now=None):
    """Store a bounded review snapshot; never change product links or labels."""
    from gadmin.deals.models import ClassificationState
    now = now or timezone.now()
    point = {'date':timezone.localtime(now,ZoneInfo('Asia/Seoul')).date().isoformat(),
             **{key:summary[key] for key in TREND_KEYS}}
    with transaction.atomic():
        state, _ = ClassificationState.objects.select_for_update().get_or_create(
            key='products:quality', defaults={'value':{}})
        history = [row for row in (state.value or {}).get('history', [])
                   if row.get('date') != point['date']]
        history.append(point)
        history = sorted(history, key=lambda row:row['date'])[-90:]
        state.value = {**summary, 'at':now.isoformat(), 'history':history}
        state.save(update_fields=['value'])
    return state.value
