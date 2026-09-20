"""A bounded timeline, with currencies and price bases kept separate."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Case, DateTimeField, F, When
from django.utils import timezone
from gadmin.deals.models import ProductPrice
from gadmin.metrics.parser import WARNING_LABELS

BASES={'offer':'판매 구성 전체','item':'낱개 1개','100g':'100g','100ml':'100ml'}


def date_bound(value, end=False):
    if not value:return None
    try:
        day=date.fromisoformat(value)
        if end:day+=timedelta(days=1)
    except (TypeError,ValueError,OverflowError):raise ValueError('기간은 YYYY-MM-DD 형식으로 입력하세요.')
    return timezone.make_aware(datetime.combine(day,time.min))


def options(product):
    currencies=list(ProductPrice.objects.filter(product=product,processed_at__isnull=False)
        .exclude(result__price__currency=None).values_list('result__price__currency',flat=True).distinct())
    currencies=sorted(code for code in currencies if isinstance(code,str) and code)
    basis='100ml' if any(size.startswith('volume_ml:') for size in product.attributes.get('sizes',[])) else (
        '100g' if any(size.startswith('weight_g:') for size in product.attributes.get('sizes',[])) else 'offer')
    return currencies,basis


def selected_amount(result, basis, shipping=False):
    price=result.get('price') or {}
    if 'conditional_price' in result.get('warnings',[]):return None
    if basis=='offer':return result.get('total_price_with_shipping') if shipping else price.get('amount')
    if result.get('status')=='review':return None
    for row in result.get('unit_prices',[]):
        if ((basis=='item' and row['basis_amount']=='1' and row['basis_unit'] in ('개','캔','병','봉','팩','정','포','매','롤','통','권'))
            or basis==row['basis_amount']+row['basis_unit']):
            return row.get('amount_with_shipping') if shipping else row.get('amount')
    return None


def history(product, params):
    currencies,default_basis=options(product)
    currency=params.get('currency') or ('KRW' if 'KRW' in currencies else (currencies[0] if currencies else 'KRW'))
    if currency not in set(currencies)|{'KRW','USD','JPY','EUR','CNY'}:raise ValueError('알 수 없는 통화입니다.')
    basis=params.get('basis') or default_basis
    if basis not in BASES:raise ValueError('알 수 없는 단가 기준입니다.')
    start,end=date_bound(params.get('start')),date_bound(params.get('end'),True)
    if start and end and start>=end:raise ValueError('시작일은 종료일보다 늦을 수 없습니다.')
    try:page=int(params.get('page','1'))
    except (TypeError,ValueError):raise ValueError('페이지 번호가 올바르지 않습니다.')
    if not 1<=page<=1000:raise ValueError('페이지 범위를 벗어났습니다. 기간을 좁혀 조회하세요.')
    shipping=params.get('shipping')=='1'
    query=ProductPrice.objects.filter(product=product).annotate(timeline_at=Case(
        When(price_revision=1,then=F('published_at')),default=F('observed_at'),output_field=DateTimeField()))
    if start:query=query.filter(timeline_at__gte=start)
    if end:query=query.filter(timeline_at__lt=end)
    count=query.count()
    limit=100
    rows=list(query.select_related('deal').order_by('-timeline_at','-id')[(page-1)*limit:page*limit])
    results=[]
    for row in rows:
        data=row.result;price=data.get('price') or {};warnings=data.get('warnings',[])
        amount=selected_amount(data,basis,shipping) if price.get('currency')==currency else None
        results.append({'id':row.pk,'deal_id':row.deal_id,'title':row.input.get('subject') or '제목 없음',
            'community':row.deal.community_name,'url':row.deal.origin_url or '',
            'at':row.timeline_at.isoformat(),'published_at':row.published_at.isoformat(),'observed_at':row.observed_at.isoformat(),
            'is_backfill':row.is_backfill,'price_revision':row.price_revision,'price':price or None,
            'quantity':data.get('quantity'),'weight_g':data.get('weight_g'),'volume_ml':data.get('volume_ml'),
            'shipping':data.get('shipping'),'amount':amount,'warnings':warnings,
            'warning_labels':[WARNING_LABELS.get(code,code) for code in warnings],
            'status':'pending' if row.processed_at is None else data.get('status','error')})
    points=[{'id':r['id'],'at':r['at'],'amount':r['amount'],'title':r['title']} for r in reversed(results) if r['amount'] is not None]
    amounts=[Decimal(p['amount']) for p in points]
    return {'product_id':str(product.pk),'currency':currency,'currencies':currencies,'basis':basis,'basis_label':BASES[basis],
        'shipping':shipping,'count':count,'page':page,'page_size':limit,'has_next':count>page*limit,
        'points':points,'results':results,'minimum':str(min(amounts)) if amounts else None,
        'maximum':str(max(amounts)) if amounts else None,
        'excluded':len(results)-len(points),'start':params.get('start',''),'end':params.get('end',''),
        'time_note':'최초 기록은 게시물 작성일, 이후 가격 변경은 확인 시각으로 표시합니다. 기존 글은 저장된 가격 1건만 복원합니다.',
        'price_note':'선택한 통화와 단가 기준만 비교합니다. 환율을 소급 적용하지 않습니다. 조건부 금액과 계산할 수 없는 값은 그래프에서 제외합니다.'}
