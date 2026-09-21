"""Extract only supported package arithmetic; keep unknown values unknown."""
from decimal import Decimal, ROUND_HALF_UP
import re

from .money import currency, decimal, price_text, string, text, title_price

VERSION = 'measurements-3'
CAPACITY_MARKERS = ('텀블러','보온병','블렌더보틀','블랜더보틀','물병','머그컵','유리컵','전기포트','냉장고','가습기','에어프라이어','에어 프라이어','쉐이커')
MEASURE = re.compile(r'(?<![\d.])(?P<n>\d+(?:\.\d+)?)\s*(?P<u>킬로그램|밀리리터|밀리그램|그램|리터|kg|mg|ml|cc|g|l)(?=$|[^A-Za-z가-힣]|x(?=\s*\d)|(?:캔|병)(?=\s|\d))', re.I)
COUNT = re.compile(r'(?<![\d.])(?P<n>\d{1,5})(?:\s*\+\s*(?P<bonus>\d{1,5}))?\s*(?P<u>캡슐|박스|세트|묶음|개입|정입|팩|캔|병|봉|포|정|매|입|개|롤|통|환|판|권)(?=$|[^A-Za-z가-힣]|[xX](?=\s*\d))')
RANK = {'입':1,'팩':2,'권':2,'박스':3,'세트':4,'묶음':4}
OUTER = set(RANK)
FACTORS = {'kg':('weight_g','1000'),'킬로그램':('weight_g','1000'),'g':('weight_g','1'),'그램':('weight_g','1'),
           'mg':('weight_g','0.001'),'밀리그램':('weight_g','0.001'),
           'l':('volume_ml','1000'),'리터':('volume_ml','1000'),'ml':('volume_ml','1'),'밀리리터':('volume_ml','1'),'cc':('volume_ml','1')}
WARNING_LABELS = {
    'quantity_options':'선택형·범위 수량이 있어 총량 계산을 보류했습니다.',
    'mixed_sizes':'서로 다른 용량·중량의 구성은 합산하지 않았습니다.',
    'ambiguous_count':'묶음 개수의 관계가 불명확해 개수 계산을 보류했습니다.',
    'total_mismatch':'표시된 총량과 묶음 계산이 일치하지 않습니다.',
    'ingredient_amount':'성분 함량은 상품 총중량에서 제외했습니다.',
    'paper_density':'종이 평량을 상품 총중량에서 제외했습니다.',
    'package_weight_ambiguous':'표시 중량이 개별 제품인지 묶음 전체인지 불명확합니다.',
    'container_capacity':'용기·기기 용량은 내용물 수량과 구분하며 100ml당 가격을 계산하지 않습니다.',
    'device_capacity':'기기 사양을 상품 중량에서 제외했습니다.',
    'gift_excluded':'사은품 수량은 상품 총량에서 제외했습니다.',
    'price_missing':'확인 가능한 상품 가격이 없습니다.',
    'currency_unknown':'통화가 명확하지 않아 단가·원화 환산을 보류했습니다.',
    'legacy_price_ignored':'수량을 가격으로 오인할 수 있는 기존 값을 계산에서 제외했습니다.',
    'legacy_foreign_precision':'과거 외화 가격은 정수로만 남아 있어 소수점 원문을 확인할 수 없습니다.',
    'conditional_price':'카드·쿠폰 등 조건이 붙은 표시 가격입니다.',
    'shipping_unknown':'배송비를 확인할 수 없어 배송비 포함 가격은 계산하지 않았습니다.',
    'shipping_currency_unknown':'배송비 통화를 확인할 수 없어 상품 금액과 합산하지 않았습니다.',
    'fx_missing':'사용할 공식 기준환율이 없습니다.',
    'fx_stale':'환율 기준일이 7일을 넘어 원화 환산을 보류했습니다.',
}


def quantities(title):
    value = text(title).replace('×','x').replace('✕','x')
    value = re.sub(r'(?<![a-z0-9])[234]\dgx\d{3}[a-z]+(?![a-z0-9])',' ',value,flags=re.I)
    warnings = []
    gift = re.search(r'\s*\+\s*[^+]*(?:증정|사은품).*$', value)
    if gift:
        value = value[:gift.start()]
        warnings.append('gift_excluded')
    # Monetary parentheses and physical specifications must not become package counts.
    value = re.sub(r'\([^()]*/[^()]*\)', '', value)
    range_or_option = bool(re.search(r'\d\s*(?:~|∼|에서|\-)\s*\d', value) and MEASURE.search(value))
    if range_or_option:
        warnings.append('quantity_options')
    totals = {}
    measures = []
    strengths = []
    for match in MEASURE.finditer(value):
        unit = match['u'].lower()
        dimension, factor = FACTORS[unit]
        amount = Decimal(match['n']) * Decimal(factor)
        if not 0 < amount <= Decimal('100000000'):
            continue
        before = value[max(0, match.start()-12):match.start()]
        if unit=='g' and amount<=300 and re.search(r'복사(?:용)?지|인쇄용지|a4\s*용지',value,re.I):
            warnings.append('paper_density')
            continue
        nutrient = re.search(r'(?:단백질|당류|지방|탄수화물|함량)\s*$',before) or re.match(r'\s*(?:단백질|당류|지방|탄수화물)',value[match.end():])
        if ((unit in ('mg','밀리그램') and not re.search(r'총\s*중량|내용량|순\s*중량', before)) or (unit in ('g','그램') and nutrient)):
            strengths.append({'amount':match['n'],'unit':'mg' if unit in ('mg','밀리그램') else 'g','evidence':match.group()})
            warnings.append('ingredient_amount')
            continue
        if unit in ('g','그램') and re.search(r'(?:ssd|ram|ddr|nvme)(?=\s|\d|$)|메모리', value,re.I) and not re.search(r'중량|무게|그램', match.group()+before):
            warnings.append('device_capacity')
            continue
        item = {'dimension':dimension,'amount':amount,'evidence':match.group(),'start':match.start(),'end':match.end()}
        if re.search(r'총(?:\s*중량|\s*용량)?\s*$',before):
            totals[dimension] = item
        else:
            measures.append(item)
    counts = []
    explicit_count = None
    for match in COUNT.finditer(value):
        before = value[max(0,match.start()-8):match.start()]
        if re.search(r'각\s*$',before):
            continue
        number = int(match['n']) + int(match['bonus'] or 0)
        if not 0 < number <= 100000:
            continue
        unit = {'개입':'개','정입':'정'}.get(match['u'],match['u'])
        item = {'count':number,'unit':unit,'evidence':match.group(),'start':match.start(),'end':match.end()}
        if re.search(r'총\s*$',before):
            explicit_count = item
        elif re.search(r'약\s*$|\d\s*[~∼-]\s*$',before):
            warnings.append('ambiguous_count')
        else:
            counts.append(item)
    # With no stated unit, a clear 1+1/2+1 offer is a same-size item count.
    bonus = re.search(r'(?<![\d.+])([1-9])\s*\+\s*([1-9])(?!\s*[\dA-Za-z가-힣])',value)
    if not counts and bonus and len(measures) == 1:
        counts = [{'count':int(bonus[1])+int(bonus[2]),'unit':'개','evidence':bonus.group(),'start':bonus.start(),'end':bonus.end()}]
    counts.sort(key=lambda row:RANK.get(row['unit'],0))
    multiplier = 1
    quantity = None
    if counts:
        # Inner count × outer packages. Repeated same-level counts are not multiplied.
        valid = len({RANK.get(row['unit'],0) for row in counts})==len(counts)
        valid = valid and not re.search(r'약\s*\d|\d\s*[~∼-]\s*\d\s*(?:개|입|팩|캔|병|매)',value)
        if valid:
            for row in counts:
                multiplier *= row['count']
            if explicit_count and len(counts)==1 and explicit_count['unit'] in OUTER and counts[0]['unit'] not in OUTER:
                multiplier *= explicit_count['count']
            if multiplier <= 1000000:
                proof=' × '.join(row['evidence'] for row in counts)
                if explicit_count and len(counts)==1 and explicit_count['unit'] in OUTER and counts[0]['unit'] not in OUTER:
                    proof+=' × 총 '+explicit_count['evidence']
                quantity = {'count':str(multiplier),'unit':counts[0]['unit'],'evidence':proof}
        if not quantity:
            warnings.append('ambiguous_count')
    elif explicit_count:
        multiplier = explicit_count['count']
        quantity = {'count':str(multiplier),'unit':explicit_count['unit'],'evidence':explicit_count['evidence']}
    result = {'weight_g':None,'volume_ml':None,'quantity':quantity,'strengths':strengths,'warnings':warnings}
    for dimension in ('weight_g','volume_ml'):
        candidates = [row for row in measures if row['dimension']==dimension]
        stated_total = totals.get(dimension)
        if len(candidates) > 1:
            warnings.append('mixed_sizes')
            continue
        if range_or_option:
            continue
        if candidates:
            row = candidates[0]
            # A count preceding a measurement is only accepted with an explicit connector.
            leading = [q for q in counts if q['end'] < row['start']]
            if leading and not re.search(r'[xX*]',value[leading[-1]['end']:row['start']]):
                warnings.append('ambiguous_count')
                continue
            if 'ambiguous_count' in warnings:
                continue
            if dimension=='weight_g' and counts and re.search(r'개입|정입|매',counts[0]['evidence']) and not re.search(r'[xX*]',value[row['end']:counts[0]['start']]):
                warnings.append('package_weight_ambiguous')
                continue
            total = row['amount'] * multiplier
            if stated_total and not counts:
                total=stated_total['amount']
            if stated_total and stated_total['amount'] != total:
                warnings.append('total_mismatch')
                continue
            result[dimension] = {'per_item':string(row['amount']),'total':string(total),'evidence':row['evidence'] + ((' × '+quantity['evidence']) if quantity else ('; 총 '+stated_total['evidence'] if stated_total else ''))}
        elif stated_total:
            result[dimension] = {'per_item':None,'total':string(stated_total['amount']),'evidence':stated_total['evidence']}
    if explicit_count and counts and quantity:
        # A stated number of outer packages can differ from an inner sheet/capsule total.
        expected = multiplier if explicit_count['unit']==quantity['unit'] else None
        if expected is not None and explicit_count['count'] != expected:
            result['quantity'] = None
            warnings.append('total_mismatch')
    if {'mixed_sizes','quantity_options','ambiguous_count','total_mismatch'}.intersection(warnings):
        result['quantity'] = None
    if {'ambiguous_count','total_mismatch'}.intersection(warnings):
        result['weight_g'] = result['volume_ml'] = None
    result['capacity_ml'] = None
    if result['volume_ml'] and any(word in value for word in CAPACITY_MARKERS) and not re.search(r'세제|세정제|살균제|청소액|향료',value):
        result['capacity_ml'] = result['volume_ml']
        result['volume_ml'] = None
        warnings.append('container_capacity')
    result['warnings'] = list(dict.fromkeys(warnings))
    return result


def analyze(snapshot):
    title = snapshot.get('subject') or ''
    result = quantities(title)
    warnings = result['warnings']
    evidence = snapshot.get('numeric_evidence') or {}
    hint = currency(evidence.get('currency') or snapshot.get('currency'))
    raw_price = evidence.get('price')
    price = price_text(raw_price, hint, bare=True) if raw_price else None
    if price:
        price['source'] = 'collected_price'
    else:
        price = title_price(title, hint)
    if price is None:
        amount = decimal(snapshot.get('price'))
        if amount and hint:
            price = {'amount':string(amount),'currency':hint,'source':'legacy_price','evidence':str(snapshot['price'])}
            if hint != 'KRW':
                warnings.append('legacy_foreign_precision')
        elif amount:
            warnings.append('legacy_price_ignored')
    if price is None:
        warnings.append('price_missing')
    elif not price['currency']:
        warnings.append('currency_unknown')
    if price and price.get('conditional'):
        warnings.append('conditional_price')
    raw_shipping = evidence.get('delivery') or (price or {}).get('shipping_text') or ''
    price_currency = (price or {}).get('currency')
    # Unknown zero in the old schema is not evidence of free delivery.
    shipping = price_text(raw_shipping,price_currency if price_currency=='KRW' else None,bare=True)
    if shipping and shipping['amount']=='0' and not shipping['currency']:
        shipping['currency'] = price_currency
    if shipping is None:
        warnings.append('shipping_unknown')
    elif shipping['currency'] != price_currency or not shipping['currency']:
        warnings.append('shipping_currency_unknown')
    total_price = None
    if price and price_currency and shipping and shipping['currency']==price_currency:
        total_price = string(Decimal(price['amount']) + Decimal(shipping['amount']))
    unit_prices = []
    if price and price_currency:
        bases = []
        for dimension, unit in (('weight_g','g'),('volume_ml','ml')):
            if result[dimension]:
                bases.append((Decimal(result[dimension]['total']),Decimal(100),unit))
        if result['quantity']:
            bases.append((Decimal(result['quantity']['count']),Decimal(1),result['quantity']['unit']))
        for total, basis, unit in bases:
            row = {'basis_amount':string(basis),'basis_unit':unit,'quantity_total':string(total),'currency':price_currency,
                   'amount':string((Decimal(price['amount'])*basis/total).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)),
                   'amount_with_shipping':None}
            if total_price is not None:
                row['amount_with_shipping'] = string((Decimal(total_price)*basis/total).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP))
            unit_prices.append(row)
    for key in ('shipping_text','conditional'):
        if price: price.pop(key,None)
    result.update(version=VERSION,price=price,shipping=shipping,total_price_with_shipping=total_price,unit_prices=unit_prices)
    result['warnings'] = list(dict.fromkeys(warnings))
    important = {'quantity_options','mixed_sizes','ambiguous_count','total_mismatch','currency_unknown','package_weight_ambiguous'}
    result['status'] = 'review' if important.intersection(warnings) else ('ready' if unit_prices else 'partial')
    return result
