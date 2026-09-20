"""Monetary evidence; a package count is never a fallback price."""
from decimal import Decimal, InvalidOperation
import re
import unicodedata

NUMBER = r'(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,4})?'
TOKEN = r'(?:US\$|USD|KRW|WON|EUR|JPY|CNY|GBP|CAD|AUD|HKD|SGD|RMB|₩|\$|€|£|¥|원|달러|유로|엔|위안)'
MONEY = re.compile(rf'(?<![\w.])(?:(?P<prefix>{TOKEN})\s*(?P<a>{NUMBER})|(?P<b>{NUMBER})\s*(?P<suffix>{TOKEN}))(?![A-Za-z\d])', re.I)
ALIASES = {'WON':'KRW','원':'KRW','₩':'KRW','US$':'USD','달러':'USD','유로':'EUR','€':'EUR','£':'GBP','엔':'JPY','위안':'CNY','RMB':'CNY'}
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
    if not value or re.search(r'~|∼|부터|이상|이하|최대|최저|%|적립|할인액|[1-9]\d*[,\d]*원?\s*무료', value):
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
        if amount is not None:
            return {'amount':string(amount),'currency':currency(match.group('prefix') or match.group('suffix'),hint),'evidence':value}
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
            continue
        left, right = group.split('/', 1)
        parsed = price_text(left, hint)
        if parsed is None:
            match = re.search(rf'(?<![\d.])({NUMBER})\s*$', left)
            if match and not re.search(r'부터|이상|~|최대|적립', left):
                parsed = price_text(match.group(1), hint or 'KRW', bare=True)
        if parsed:
            parsed.update(source='title', shipping_text=right.strip(), conditional=bool(re.search(r'카드|쿠폰|코인|티멤|유클|멤버|페이',left)))
            return parsed
    matches = list(MONEY.finditer(title))
    if len(matches) == 1 and not re.search(r'정가|이상|부터|적립|할인|금액권|상품권|교환권|쿠폰|(?:g|ml|개|팩)\s*당',title,re.I):
        match = matches[0]
        parsed = price_text(match.group(), hint)
        if parsed:
            return {**parsed,'source':'title','shipping_text':'','conditional':False}
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
