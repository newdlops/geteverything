"""Monetary evidence; a package count is never a fallback price."""
from decimal import Decimal, InvalidOperation
import re
import unicodedata

NUMBER = r'(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,4})?'
TOKEN = r'(?:US\$|USD|KRW|WON|EUR|JPY|CNY|GBP|CAD|AUD|HKD|SGD|RMB|₩|\$|€|£|¥|만원|천원|만|천|원|달러|유로|엔|위안)'
PREFIX_TOKEN = r'(?:US\$|USD|KRW|WON|EUR|JPY|CNY|GBP|CAD|AUD|HKD|SGD|RMB|₩|\$|€|£|¥|만원|천원|원|달러|유로|엔|위안)'
MONEY = re.compile(rf'(?<![\d.,])(?:(?P<prefix>{PREFIX_TOKEN})\s*(?P<a>{NUMBER})|(?P<b>{NUMBER})\s*(?P<suffix>{TOKEN}))(?![A-Za-z\d])', re.I)
ALIASES = {'WON':'KRW','원':'KRW','₩':'KRW','만원':'KRW','만':'KRW','천원':'KRW','천':'KRW','US$':'USD','달러':'USD','유로':'EUR','€':'EUR','£':'GBP','엔':'JPY','위안':'CNY','RMB':'CNY'}
CODES = {'KRW','USD','EUR','JPY','CNY','GBP','CAD','AUD','HKD','SGD','CHF','NZD','THB','VND'}


def text(value):
    return unicodedata.normalize('NFKC', str(value or '')).strip()[:1024]


def decimal(value):
    try:
        number = Decimal(str(value).replace(',', ''))
        if number.is_finite() and 0 <= number <= Decimal('1000000000000'):
            return number
    except (InvalidOperation, ValueError, TypeError):
        pass
    return None


def competing_amounts(value, match):
    """Whether a title context contains another unlabelled monetary number."""
    residue = value[:match.start()] + ' ' + value[match.end():]
    residue = re.sub(rf'{NUMBER}\s*%', ' ', residue)
    residue = re.sub(rf'{NUMBER}\s*(?:kg|g|ml|l|gb|tb|개|통|팩|병|매|알|포|정|인분|개월|종)\b', ' ', residue, flags=re.I)
    return bool(re.search(NUMBER, residue))


def voucher_sale_price(value, hint=None):
    """Pick a sale amount beside one explicitly marked gift-card face value."""
    amounts = list(MONEY.finditer(value))
    face_values = [m for m in amounts if re.match(r'\s*권', value[m.end():])]
    sale_values = [m for m in amounts if m not in face_values]
    if len(amounts) != 2 or len(face_values) != 1 or len(sale_values) != 1:
        return None
    sale = sale_values[0]
    token = (sale.group('prefix') or sale.group('suffix') or '').upper()
    if token not in {'원','KRW','WON'}:
        return None
    residue = value[:face_values[0].start()] + ' ' + value[face_values[0].end():sale.start()] + ' ' + value[sale.end():]
    residue = re.sub(rf'{NUMBER}\s*%', ' ', residue)
    if re.search(NUMBER, residue):
        return None
    return price_text(sale.group(), hint or 'KRW')


def string(value):
    return format(value, 'f').rstrip('0').rstrip('.') if '.' in format(value, 'f') else format(value, 'f')


def currency(value, hint=None):
    code = text(value).upper()
    if code == '$':
        return hint if hint in {'USD','CAD','AUD','HKD','SGD','NZD'} else None
    if code == '¥':
        return hint if hint in {'JPY','CNY'} else None
    return ALIASES.get(code, code if code in CODES else None)


def price_text(value, hint=None, bare=False):
    """Parse one price field, not a title containing unrelated numbers."""
    value = text(value)
    hint = currency(hint)
    if not value or re.search(r'~|∼|부터|이상|이하|최대|최저|적립|할인액|[1-9]\d*[,\d]*원?\s*무료', value):
        return None
    if value in ('무료','무료배송','무배','무료배포','free'):
        return {'amount':'0','currency':hint,'evidence':value}
    matches = list(MONEY.finditer(value))
    if len(matches) == 1:
        match = matches[0]
        remainder = (value[:match.start()] + value[match.end():]).strip(' ()[]')
        if re.search(r'[\d$€¥₩]|정가|대신|/|\+|→', remainder):
            return None
        amount = decimal(match.group('a') or match.group('b'))
        token = (match.group('prefix') or match.group('suffix') or '').upper()
        if token in {'만원','만'}:
            amount = amount * 10000 if amount is not None else None
        elif token in {'천원','천'}:
            amount = amount * 1000 if amount is not None else None
        if amount is not None:
            return {'amount':string(amount),'currency':currency(token,hint),'evidence':value}
    if bare and re.fullmatch(NUMBER, value):
        amount = decimal(value)
        if amount is not None and amount > 0:
            return {'amount':string(amount),'currency':hint,'evidence':value}
    return None


def title_price(title, hint=None):
    """A final (price/shipping) expression outranks other numbers in a title."""
    title = text(title)
    # Slash-separated shipping is the established title convention on these sites.
    groups = re.findall(r'\(([^()]*)\)', title)
    for group in reversed(groups):
        if '/' not in group:
            # Some communities put product price and delivery price in the
            # same parentheses without a slash, e.g. "(12,650원 3,000원)".
            # Accept only two explicit KRW amounts with no intervening words;
            # other multi-price titles remain ambiguous.
            amounts = list(MONEY.finditer(group))
            if len(amounts) == 2:
                first, second = amounts
                residue = group[:first.start()] + group[first.end():second.start()] + group[second.end():]
                explicit_krw = all((m.group('suffix') or '').upper() in ('원','KRW','WON') for m in amounts)
                if explicit_krw and not re.search(r'[A-Za-z가-힣%~∼/+→]', residue):
                    parsed = price_text(first.group(), hint or 'KRW')
                    shipping = price_text(second.group(), hint or 'KRW')
                    if parsed and shipping:
                        parsed.update(source='title', shipping_text=shipping['evidence'], conditional=False)
                        return parsed
            continue
        left, right = group.split('/', 1)
        parsed = price_text(left, hint)
        conditional = bool(re.search(r'카드|쿠폰|코인|티멤|유클|멤버|페이|적용가|할인가',left))
        if parsed is None:
            # Product titles commonly put a coupon percentage before the one
            # explicit won amount. The currency marker identifies the price;
            # the percentage is a condition, not a competing amount.
            amounts = list(MONEY.finditer(left))
            if len(amounts) == 1 and not competing_amounts(left, amounts[0]) and not re.search(r'적립|할인액|최대|최저|정가',left):
                parsed = price_text(amounts[0].group(), hint or 'KRW')
                conditional = conditional or bool(re.search(r'%|부터|이상|~|∼|쿠폰|카드|코인|티멤|유클|멤버|페이|적용가|할인가',left))
        if parsed is None:
            parsed = voucher_sale_price(left, hint)
            if parsed:
                conditional = conditional or bool(re.search(r'쿠폰|카드|코인|티멤|유클|멤버|페이|적용가|할인가',left))
        if parsed is None:
            match = re.search(rf'(?<![\d.])({NUMBER})\s*$', left)
            if match and not re.search(r'부터|이상|~|최대|적립', left):
                parsed = price_text(match.group(1), hint or 'KRW', bare=True)
        if parsed is None:
            # A single explicitly labelled "from" price is a real lower-bound
            # price, not an unknown package count. Keep it as conditional so
            # callers can distinguish it from an exact fixed price.
            amounts = list(MONEY.finditer(left))
            if len(amounts) == 1 and re.search(r'(?:부터|이상|~|∼)\s*$',left) and not re.search(r'적립|할인액|최대|최저',left):
                parsed = price_text(amounts[0].group(), hint)
                conditional = True
        if parsed:
            conditional = conditional or bool(re.search(r'만원대|천원대|원대|\d\s*만대|초반|중반|후반|내외',left))
            parsed.update(source='title', shipping_text=right.strip(), conditional=conditional)
            return parsed
    # Some sources omit parentheses around the same explicit price/shipping
    # convention, e.g. "... 459,370원부터/무료배송".
    if '/' in title:
        left, right = title.rsplit('/', 1)
        amounts = list(MONEY.finditer(left))
        if len(amounts) == 1 and re.search(r'(?:부터|이상|~|∼)\s*$',left) and not re.search(r'적립|할인액|최대|최저|정가',left):
            parsed = price_text(amounts[0].group(), hint or 'KRW')
            if parsed:
                parsed.update(source='title', shipping_text=right.strip(), conditional=True)
                return parsed
    voucher = voucher_sale_price(title, hint)
    if voucher:
        conditional = bool(re.search(r'쿠폰|카드|코인|티멤|유클|멤버|페이|적용가|할인가',title))
        return {**voucher,'source':'title','shipping_text':'','conditional':conditional}
    matches = list(MONEY.finditer(title))
    if len(matches) == 1 and not re.search(r'정가|이상|부터|적립|할인|바우처|금액권|상품권|교환권|쿠폰|(?:원|만원|천원)\s*권|(?:g|ml|개|팩)\s*당|/[^()]*\d',title,re.I):
        match = matches[0]
        parsed = price_text(match.group(), hint)
        if parsed:
            context = title[max(0, match.start()-24):min(len(title), match.end()+8)]
            conditional = bool(re.search(r'만원대|천원대|원대|\d\s*만대|초반|중반|후반|내외|체감가',context))
            return {**parsed,'source':'title','shipping_text':'','conditional':conditional}
    return None


def legacy_subject_price(title):
    """Keep the crawler's old numeric-text contract without matching package counts."""
    parsed = title_price(title, 'KRW')
    if parsed and parsed['currency'] == 'KRW':
        return parsed['amount']
    # Legacy titles sometimes give original and discounted won amounts explicitly.
    matches = [m for m in MONEY.finditer(text(title)) if (m.group('suffix') or '').upper() in ('원','KRW','WON')]
    if matches and not re.search(r'이상|적립|금액권|상품권|쿠폰\s*\d', text(title)):
        return string(decimal(matches[-1].group('a') or matches[-1].group('b')))
    return 0
