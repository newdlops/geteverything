"""Serialize product registry changes before locking assignments or price rows."""
from gadmin.deals.models import ClassificationState, DealProduct, Product, ProductMatchExample, ProductPrice
from . import identity


def lock():
    # Call inside transaction.atomic, before taking any assignment/product locks.
    return ClassificationState.objects.select_for_update().get_or_create(
        key='products:catalog', defaults={'value': {}})[0]


def canonical(product):
    seen = set()
    while product.merged_into_id:
        if product.pk in seen:
            raise ValueError('상품 통합 연결을 확인하세요.')
        seen.add(product.pk)
        product = Product.objects.get(pk=product.merged_into_id)
    return product


def automatic(data, category=''):
    """Caller holds the catalog lock. Missing packaging is a partial observation."""
    key=identity.signature(data)
    keys=identity.container_keys(data)
    if keys:
        rows={row.identity_key:row for row in Product.objects.filter(is_active=True,identity_key__in=keys.values())}
        known={kind:rows[value] for kind,value in keys.items() if kind and value in rows}
        container=data['attributes'].get('container','')
        if not container and len(known)==1:
            return next(iter(known.values()))
        # Enrich the existing UUID when the first explicit container arrives.
        unknown=rows.get(keys[''])
        if container and not known and unknown and not protected(unknown):
            unknown.identity_key=key
            unknown.attributes=data['attributes']
            unknown.name=identity.display_name(data)
            unknown.save(update_fields=['identity_key','attributes','name','updated_at'])
            return unknown
    product,_=Product.objects.get_or_create(identity_key=key,defaults={
        'name':identity.display_name(data),'brand':data.get('brand',''),'model':data.get('model',''),
        'attributes':data['attributes'],'category':category})
    product=canonical(product)
    if not product.is_active:
        product.is_active=True
        product.save(update_fields=['is_active','updated_at'])
    return product


def protected(product):
    return (product.verified or DealProduct.objects.filter(product=product,manual_override=True).exists()
        or ProductPrice.objects.filter(product=product,deal__product_assignment__manual_override=True).exists()
        or ProductMatchExample.objects.filter(product=product).exists())
