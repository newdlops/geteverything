import hashlib
import html
import json
import re
import unicodedata
from decimal import Decimal

from gadmin.metrics.parser import COUNT, MEASURE, quantities

VERSION = 'products-6'
SHOP_TAGS={'쿠팡','네이버','네이버쇼핑','지마켓','g마켓','gmarket','옥션','11번가','알리','알리익스프레스',
           'aliexpress','아마존','amazon','티몬','위메프','g9','쇼핑몰','스토어','shop','기타'}
MULTI_PRODUCT = re.compile(r'골라\s*담|택\s*1|선택형|중\s*선택|모음전|외\s*\d+\s*종|\d+\s*종\s*(?:중|택)|'
                           r'\+\s*(?=[a-z가-힣])(?!(?:무료(?:배송)?|무배|배송|사은품|증정)(?:\b|$))')
BRANDS = {
    '삼성': 'samsung', 'samsung': 'samsung', '엘지': 'lg', 'lg': 'lg',
    '에이엠디': 'amd', 'amd': 'amd', '애플': 'apple', 'apple': 'apple',
    '코카콜라': 'cocacola', '코카 콜라': 'cocacola', 'coca-cola': 'cocacola',
    '펩시': 'pepsi', 'pepsi': 'pepsi', '씨제이': 'cj', 'cj': 'cj',
    '매일':'maeil','매일두유':'maeil','매일유업':'maeil','광동':'kwangdong','나이키':'nike','로지텍':'logitech',
    '오뚜기':'ottogi','농심':'nongshim','롯데':'lotte','삼양':'samyang','동원':'dongwon','아디다스':'adidas',
}
GENERIC_BRANDS={'두유','우유','콜라','음료','검은콩','생수','쌀','식품','냉동','저당','제로','라임','상품','무선','유선',
                '알카라인','건전지','텀블러','프리워크아웃','로봇청소기','무선청소기',
                '무료','무배','배송','쿠폰','카드','네멤','네멤무배','와우','지마켓','쿠팡','네이버','티멤',
                '법성포','영광','완도','제주','해남','횡성','국내산','국산','수입산','미국산','호주산'}
OPTIONS = {
    'zero': r'제로|\bzero\b', 'diet': r'다이어트|\bdiet\b',
    'lime': r'라임|\blime\b', 'lemon': r'레몬|\blemon\b',
    'cherry': r'체리|\bcherry\b', 'vanilla': r'바닐라|\bvanilla\b',
    'decaf': r'디카페인|\bdecaf\b', 'original': r'오리지널|\boriginal\b',
    'caffeine_free': r'무카페인|카페인\s*프리|제로[\s-]*제로|제로\s*카페인', 'mango': r'망고|\bmango\b',
    'peach': r'복숭아|\bpeach\b', 'grape': r'포도|\bgrape\b', 'yuzu': r'유자|\byuzu\b',
    'brown_rice': r'현미', 'black_rice': r'흑미', 'multi_grain': r'잡곡',
    'black': r'블랙|검정|\bblack\b', 'white': r'화이트|흰색|\bwhite\b',
    'silver': r'실버|\bsilver\b', 'blue': r'블루(?!투스)|파랑|\bblue\b',
    'red': r'(?<![가-힣])레드|빨강|\bred\b', 'pink': r'핑크|\bpink\b',
    'refurbished': r'리퍼|리퍼비시|중고|\brefurb',
    'battery_aa': r'(?<![a-z])aa(?![a-z])', 'battery_aaa': r'(?<![a-z])aaa(?![a-z])',
    'male': r'남성|남자|맨즈|\bmen.s\b', 'female': r'여성|여자|우먼|\bwomen.s\b',
}
SPEC = re.compile(r'(?<![a-z0-9.])(\d+(?:\.\d+)?)\s*(tb|gb|mhz|ghz|hz|인치|inch|mm|cm|w|mah|mg)\b', re.I)
KNOWN_MODEL = re.compile(r'(?<![a-z0-9])(?:9(?:80|90|100)\s*(?:pro|evo)(?:\s*plus)?|[579]\d{3}x3d|[234]\d(?:gp|gr|gs|gx|un|uq)\d{2,3}[a-z]+|aw\d{4}[a-z]+)(?![a-z0-9])', re.I)
MONITOR_MODEL = re.compile(r'(?<![a-z0-9])[234]\d[a-z]{1,3}\d{2,3}[a-z]*(?![a-z0-9])', re.I)
PC_OFFER = re.compile(r'완\s*본(?:체)?|반\s*본체|본체|조립\s*(?:pc|피씨|컴퓨터|컴)|게이밍\s*(?:pc|컴퓨터)|서린컴퓨터|(?<![a-z가-힣])pc(?![a-z가-힣])', re.I)
ACCESSORIES = {'case':r'케이스|커버|파우치','protector':r'보호\s*필름|강화\s*유리',
               'heatsink':r'방열판|히트싱크','skin':r'스킨|스티커','stand':r'거치대|마운트'}


def normalize(value):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', html.unescape(value or '')).casefold()).strip()


def compact(value):
    return re.sub(r'[^a-z0-9가-힣]', '', normalize(value))


def clean_title(title):
    value = normalize(title).replace('×', 'x')
    value = re.sub(r'\[([^\]]{1,50})\]',lambda m:' ' if compact(m[1]) in SHOP_TAGS else ' '+m[1]+' ',value)
    def price_parenthesis(match):
        body=match[1]
        if not re.search(r'원|무배|무료|배송|\$|usd|krw',body):return match[0]
        body=re.sub(r'[$€¥]\s*\d[\d,]*(?:\.\d+)?|\d[\d,]*(?:\.\d+)?\s*(?:원|달러|usd|krw|jpy|eur)|(?<![a-z0-9])\d[\d,]*(?=\s*/)', ' ',body)
        body=re.sub(r'무료배송|무료\s*배송|무배|무료|배송비?', ' ',body)
        return ' '+body+' '
    value = re.sub(r'\(([^()]*)\)',price_parenthesis,value)
    if re.search(r'임박|소비기한|유통기한',value):
        value=re.sub(r'(?<!\d)(?:20)?\d{2}[./-]\d{1,2}[./-]\d{1,2}(?!\d)',' ',value)
    value = re.sub(r'\s*\+\s*[^+]*(?:증정|사은품).*$', '', value)
    value = re.sub(r'(?<!\d)\d[\d,]*(?:\.\d+)?\s*(?:원|달러)(?:대|부터|~)?', ' ', value)
    value = re.sub(r'무료배송|무배|역대가|특가|오늘끝딜|타임딜|카드할인|즉시할인', ' ', value)
    return re.sub(r'\s+', ' ', value).strip()


def alias_title(title):
    value = clean_title(title)
    value = COUNT.sub(' ', value)
    value = re.sub(r'(?<![a-z0-9.])\d+\s*\+\s*\d+(?![a-z0-9.])', ' ', value)
    return compact(value)


def title_hash(title):
    return hashlib.sha256(normalize(title).encode()).hexdigest()


def cache_hash(title):
    return hashlib.sha256(alias_title(title).encode()).hexdigest()


def offer_issue(title):
    # Inspect the original title before removing gifts: a PC + game is still a PC.
    value = normalize(title)
    models = {compact(match.group()) for match in KNOWN_MODEL.finditer(value)}
    if re.search(r'\d+\s*/\s*\d+\s*(?:캔|개|입|팩|병)|오리지널\s*[/,]\s*제로|제로\s*[/,]\s*오리지널',value):
        return 'not_a_single_product'
    if re.search(r'\baa\b', value) and re.search(r'\baaa\b', value):
        return 'not_a_single_product'
    if re.search(r'(?:맛|향|색상|사이즈|규격)\s*선택|기타\s*옵션', value):
        return 'not_a_single_product'
    if re.search(r'(?<![가-힣])매움(?![가-힣])', value) and re.search(r'더\s*매움', value):
        return 'not_a_single_product'
    cleaned = clean_title(title)
    if len(list(COUNT.finditer(cleaned))) > 1 and re.search(r'(?:팩|개|캔|병|봉|입|포)\s*[,/]\s*[가-힣a-z]', cleaned):
        return 'not_a_single_product'
    # Food choice listings can omit punctuation between the different products.
    food_types = [r'윙봉|버팔로윙|버팔로봉', r'가[라리]아게', r'치킨너겟', r'닭가슴살', r'닭다리']
    if sum(bool(re.search(kind, cleaned)) for kind in food_types) > 1:
        return 'not_a_single_product'
    if any(model.endswith('x3d') for model in models):
        if PC_OFFER.search(value) or re.search(r'(?:rtx|gtx|rx)\s*\d{3,4}|\+\s*\d', value):
            return 'not_a_single_product'
        if re.search(r'\d+\s*(?:gb|tb)(?![a-z0-9])|\b(?:b|x)[5678]\d{2}[a-z]*\b', value):
            return 'not_a_single_product'
        if len(set(re.findall(r'(?<![a-z0-9])[579]\d{3}(?:x3d|[xfgt]+)(?![a-z0-9])',value)))>1:
            return 'not_a_single_product'
    if len(models) > 1:
        return 'not_a_single_product'
    if any(re.match(r'[234]\d(?:gp|gr|gs|gx|un|uq)|aw\d', model) for model in models):
        if len({compact(m.group()) for m in MONITOR_MODEL.finditer(value)}) > 1:
            return 'not_a_single_product'
        if re.search(r'\d+\s*종|(?:모니터|oled)[^/]*[/,][^/]*(?:모니터|게이밍|인치)|외\s*(?:다수|다양)', value):
            return 'not_a_single_product'
    if MULTI_PRODUCT.search(clean_title(title)):
        return 'not_a_single_product'
    return ''


def canonical_data(data):
    """A manufacturer's complete SKU determines fixed hardware specifications."""
    result = {**data, 'attributes': dict(data.get('attributes') or {})}
    model = normalize(result.get('model'))
    attributes = result['attributes']
    if KNOWN_MODEL.fullmatch(model) and not attributes.get('accessory_kind'):
        model = compact(model)
        brand = ('amd' if model.endswith('x3d') else 'samsung' if re.match(r'9(?:80|90|100)(?:pro|evo)', model)
                 else 'dell' if model.startswith('aw') else 'lg')
        # Capacity distinguishes SSDs of the same family. Clocks, screen size and
        # promotional dates do not distinguish a complete CPU/monitor model code.
        specs = sorted(set(spec for spec in attributes.get('specs', [])
                           if brand == 'samsung' and re.fullmatch(r'[\d.E+]+(?:gb|tb)', spec, re.I)))
        attributes = {'sizes': [], 'options': [option for option in attributes.get('options', []) if option == 'refurbished'],
                      'specs': specs, 'numeric_options': []}
        result.update(brand=brand, name=model, model=model, variant='', attributes=attributes)
    return result


OPTION_LABELS = {'zero':'제로', 'diet':'다이어트', 'lime':'라임', 'lemon':'레몬', 'cherry':'체리',
    'vanilla':'바닐라', 'decaf':'디카페인', 'original':'오리지널', 'caffeine_free':'무카페인',
    'mango':'망고', 'peach':'복숭아', 'grape':'포도', 'brown_rice':'현미', 'black_rice':'흑미',
    'multi_grain':'잡곡', 'yuzu':'유자', 'black':'블랙', 'white':'화이트', 'silver':'실버', 'blue':'블루',
    'red':'레드', 'pink':'핑크', 'refurbished':'리퍼·중고', 'male':'남성', 'female':'여성'}


def display_name(data):
    data = canonical_data(data)
    parts = list(dict.fromkeys(filter(None, [data.get('brand'), data.get('name'), data.get('variant')])))
    attributes = data.get('attributes', {})
    for option in attributes.get('options', []):
        label = OPTION_LABELS.get(option, option)
        if not re.search(OPTIONS.get(option, re.escape(label)), normalize(' '.join(parts))):
            parts.append(label)
    for size in attributes.get('sizes', []):
        kind, _, value = size.partition(':')
        label = format(Decimal(value), 'f') + ('g' if kind == 'weight_g' else 'ml')
        if compact(label) not in compact(' '.join(parts)):
            parts.append(label)
    parts.extend(spec.upper() for spec in attributes.get('specs', []) if compact(spec) not in compact(' '.join(parts)))
    if attributes.get('container'):
        parts.append(CONTAINER_LABELS.get(attributes['container'], attributes['container']))
    return ' '.join(parts)[:240]


def facts(title):
    value = clean_title(title)
    value = re.sub(r'(\d)(kg|mg|ml|cl|l|g)(?=세트|묶음|구성)', r'\1\2 ', value, flags=re.I)
    # In LG model numbers, GX followed by digits is not grams × quantity.
    quantity_value=re.sub(r'(?<![a-z0-9])[234]\dgx\d{3}[a-z]+(?![a-z0-9])',' ',value)
    parsed = quantities(quantity_value)
    result = {'sizes': [], 'options': sorted(code for code, pattern in OPTIONS.items() if re.search(pattern, value)), 'specs': []}
    for dimension in ('weight_g', 'volume_ml', 'capacity_ml'):
        if parsed.get(dimension) and parsed[dimension].get('per_item'):
            result['sizes'].append(dimension + ':' + str(Decimal(parsed[dimension]['per_item']).normalize()))
    result['specs'] = sorted({str(Decimal(m[1]).normalize()) + m[2].lower() for m in SPEC.finditer(value)})
    # Preserve unrecognised numeric model/option tokens; never let a model omit S24 vs S25.
    remaining = MEASURE.sub(' ', COUNT.sub(' ', quantity_value))
    remaining += ' '+' '.join(re.findall(r'(?<![a-z0-9])[234]\dgx\d{3}[a-z]+(?![a-z0-9])',value))
    remaining = SPEC.sub(' ', remaining)
    remaining = re.sub(r'(?<![a-z0-9.])\d+\s*\+\s*\d+(?![a-z0-9.])', ' ', remaining)
    remaining = re.sub(r'\b[xX]\s*\d+\b', ' ', remaining)
    result['numeric_options'] = sorted({token for token in re.findall(r'[a-z0-9]+(?:[.-][a-z0-9]+)*', remaining)
                                        if re.search(r'\d', token)})
    accessories=sorted(key for key,pattern in ACCESSORIES.items() if re.search(pattern,value))
    if accessories:result['accessory_kind']=accessories
    if re.search(r'페트|(?<![a-z])pet(?![a-z])', value): result['container'] = 'pet'
    elif re.search(r'유리\s*병', value): result['container'] = 'glass'
    elif re.search(r'종이\s*팩|테트라\s*팩', value): result['container'] = 'carton'
    elif re.search(r'(?<![가-힣])캔(?![가-힣])|\d+\s*캔|캔\s*\d+', value): result['container'] = 'can'
    elif re.search(r'(?<![가-힣])병(?![가-힣])|\d+\s*병', value): result['container'] = 'bottle'
    return result


def signature(data):
    data = canonical_data(data)
    value = [BRANDS.get(normalize(data.get('brand')), compact(data.get('brand'))),
             compact(data.get('model') or data.get('name')), compact(data.get('variant')), data.get('attributes', {})]
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


CONTAINER_LABELS = {'can':'캔', 'pet':'페트', 'glass':'유리병', 'carton':'종이팩', 'bottle':'병'}


def with_container(data, container):
    result=canonical_data(data)
    result['attributes'].pop('container',None)
    if container:result['attributes']['container']=container
    return result


def container_keys(data):
    """Only missing packaging may vary; product line, flavor and volume stay exact."""
    attributes=data.get('attributes') or {}
    sizes=attributes.get('sizes',[])
    if len(sizes)!=1 or not sizes[0].startswith('volume_ml:') or attributes.get('accessory_kind'):
        return {}
    return {kind:signature(with_container(data,kind)) for kind in ('',*CONTAINER_LABELS)}


def compatible(left, right):
    return canonical_data(left).get('attributes', {}) == canonical_data(right).get('attributes', {})


def grounded(title, data):
    if offer_issue(title):
        return None, 'not_a_single_product'
    if not isinstance(data, dict) or data.get('is_product') is not True:
        return None, 'not_a_single_product'
    fields = {key: str(data.get(key) or '').strip() for key in ('brand','name','model','variant')}
    source = compact(title)
    limits={'brand':100,'model':120,'name':160,'variant':160}
    if not fields['name'] or any(len(value)>limits[key] or (value and compact(value) not in source) for key,value in fields.items()):
        return None, 'ungrounded_product_fields'
    if len(compact(fields['name']))<3 or compact(fields['name']) in {'상품','제품','세트','식품','음료','콜라','노트북','모니터','할인','쿠폰'}:
        return None, 'identity_not_specific'
    if not fields['brand'] and not fields['model'] and len(compact(fields['name']))<6:
        return None, 'identity_not_specific'
    if not fields['brand'] and not (fields['model'] and re.search(r'\d',fields['model'])):
        return None, 'brand_or_model_missing'
    brand=normalize(fields['brand'])
    if brand and (brand in GENERIC_BRANDS or (brand not in BRANDS and not re.search(
            r'(?<![a-z0-9가-힣])'+re.escape(brand)+r'(?![a-z0-9가-힣])',normalize(title)))):
        return None, 'brand_not_specific'
    if fields['model'] and (not re.search(r'\d',fields['model']) or not re.search(r'[a-z]',fields['model'],re.I) or MEASURE.fullmatch(fields['model'])
                            or SPEC.fullmatch(fields['model']) or COUNT.search(fields['model'])):
        return None, 'model_not_identifier'
    if MEASURE.search(fields['variant']) or COUNT.search(fields['variant']) or SPEC.search(fields['variant']):
        return None, 'quantity_in_variant'
    if COUNT.search(fields['name']):return None, 'quantity_in_product_name'
    if not fields['model'] and compact(fields['name'])==compact(fields['brand']):
        return None, 'product_line_missing'
    parsed = quantities(clean_title(title))
    if {'mixed_sizes','quantity_options','total_mismatch','ambiguous_count'}.intersection(parsed['warnings']):
        return None, 'mixed_or_ambiguous_package'
    fields['attributes'] = facts(title)
    fields['category'] = data.get('category') or ''
    return canonical_data(fields), ''


def extract_rule(title):
    value = clean_title(title)
    if offer_issue(title):return None
    model = KNOWN_MODEL.search(value)
    if model and not facts(title).get('accessory_kind'):
        preferred=('amd','에이엠디') if model.group().endswith('x3d') else (
            ('삼성','samsung') if re.match(r'9(?:80|90|100)',model.group()) else (
            ('dell','델') if model.group().startswith('aw') else ('lg','엘지')))
        brand = next((name for name in preferred if name in value), '')
        data = {'is_product': True, 'name': model.group(), 'model': model.group(), 'brand': brand}
        return grounded(title, data)[0]
    for pattern in (r'(?:코카\s*콜라|coca-cola)', r'(?:펩시|pepsi)', r'햇반'):
        match = re.search(pattern, value)
        if match and not re.search(r'기프티|교환권|쿠폰|키링|굿즈|골라|택\s*1|\s\+\s', value):
            if not facts(title)['sizes']:
                continue
            # Only recognise the simple named product. An unrecognised sub-line goes to the model.
            remainder = value[:match.start()]+' '+value[match.end():]
            remainder = MEASURE.sub(' ', COUNT.sub(' ', remainder))
            for option in OPTIONS.values():remainder=re.sub(option,' ',remainder)
            remainder=re.sub(r'\b[xX]\s*\d+\b|\d+\s*\+\s*\d+|캔당|개당|유리\s*병|종이\s*팩|테트라\s*팩|캔|페트|(?<![a-z])pet(?![a-z])|병|cj|씨제이', ' ', remainder)
            if re.search(r'[a-z가-힣]',remainder):continue
            if {'mixed_sizes','quantity_options','total_mismatch','ambiguous_count'}.intersection(quantities(value)['warnings']):continue
            data = {'is_product': True, 'name': match.group(), 'brand': match.group()}
            # These short established product names are sufficient with a physical size.
            attributes=facts(title)
            loose_count=re.search(r'(?:ml|kg|g|l)[\s,]+(\d+)[\s/()]*$',value)
            if loose_count:
                attributes['numeric_options']=[token for token in attributes['numeric_options'] if token!=loose_count[1]]
            return {key: data.get(key, '') for key in ('name','brand','model','variant')} | {'attributes':attributes,'category':''}
    return None
