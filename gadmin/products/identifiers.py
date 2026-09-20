"""Extract namespaced merchant identifiers without treating listings as global SKUs."""
import base64
import hashlib
import html
import json
import re
from urllib.parse import parse_qs, unquote, urlencode, urlsplit, urlunsplit

VERSION = 'merchant-identifiers-1'
SHORT_HOSTS = {'naver.me', 'link.coupang.com', 'coupa.ng', 'link.gmarket.co.kr',
               's.lotteon.com', 'toss.shopping', 'toss.im', 'c11.kr', 'bit.ly'}
WRAPPERS = {'s.ppomppu.co.kr', 'link.fmkorea.org', 'link.fmkorea.com',
            'click.linkprice.com', 'www.linkprice.com', 'unsafelink.com', 'www.unsafelink.com'}


def public_url(value):
    if not isinstance(value, str) or len(value) > 4096:
        return ''
    value = html.unescape(value).strip()
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username
                or parsed.password or parsed.port not in {None, 80, 443}
                or any(ord(c) < 33 for c in value)):
            return ''
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or '/', parsed.query, ''))
    except ValueError:
        return ''


def decode_target(value):
    for _ in range(3):
        if public_url(value):
            return public_url(value)
        decoded = unquote(value)
        if decoded == value:
            break
        value = decoded
    try:
        return public_url(base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True).decode())
    except (ValueError, UnicodeError):
        return ''


def unwrap(value):
    value = public_url(value)
    seen = set()
    for _ in range(5):
        if not value or value in seen:
            break
        seen.add(value)
        parsed = urlsplit(value)
        host = parsed.hostname.lower()
        target = ''
        if host in {'unsafelink.com', 'www.unsafelink.com'}:
            target = decode_target(parsed.path.lstrip('/') + ('?' + parsed.query if parsed.query else ''))
        if not target and host in WRAPPERS:
            query = parse_qs(parsed.query)
            target = next((decode_target(query[key][0]) for key in ('url', 'target', 'tu', 'u', 'redirect', 'redirect_url')
                           if len(query.get(key, [])) == 1 and decode_target(query[key][0])), '')
        if not target:
            break
        value = target
    return value


def identifier(namespace, scope, value, url, *, rank=1):
    raw = [namespace, scope, value]
    return {'namespace': namespace, 'scope': scope, 'value': value, 'canonical_url': url,
            'key': hashlib.sha256(json.dumps(raw, separators=(',', ':')).encode()).hexdigest(), 'rank': rank}


def extract(value):
    url = unwrap(value)
    if not url:
        return []
    parsed = urlsplit(url)
    host, path = parsed.hostname.lower(), parsed.path
    query = {}
    for key, values in parse_qs(parsed.query).items():
        query.setdefault(key.lower(), []).extend(values)
    def parameter(*names, pattern=r'[0-9]+'):
        for name in names:
            values = query.get(name.lower(), [])
            if len(values) == 1 and re.fullmatch(pattern, values[0]) and len(values[0]) <= 128:
                return values[0]
        return ''
    def found(namespace, number, canonical, scope='', variant=''):
        if len(number) > 128 or len(scope) > 128 or len(canonical) > 512:
            return []
        rows = [identifier(namespace, scope, number, canonical)]
        if variant and len(number + ':' + variant) <= 256:
            rows.append(identifier(namespace + '.variant', scope, number + ':' + variant, canonical, rank=2))
        return rows
    match = re.fullmatch(r'/([^/]+)/products/(\d+)/?', path)
    if host in {'smartstore.naver.com', 'brand.naver.com', 'm.smartstore.naver.com', 'm.brand.naver.com'} and match:
        shop, number = match.groups()
        return found('naver', number, f'https://smartstore.naver.com/{shop}/products/{number}', shop.lower(),
                     parameter('optionCombinationId', 'optionId'))
    match = re.fullmatch(r'/(?:vp/)?products/(\d+)/?', path)
    if host in {'coupang.com', 'www.coupang.com', 'm.coupang.com'} and match:
        number = match[1]
        options = {key: parameter(key) for key in ('itemId', 'vendorItemId') if parameter(key)}
        canonical = f'https://www.coupang.com/vp/products/{number}' + ('?' + urlencode(options) if options else '')
        rows = found('coupang.product', number, canonical)
        for key, kind, rank in [('itemId', 'item', 2), ('vendorItemId', 'vendor_item', 3)]:
            if key in options:
                rows.append(identifier('coupang.' + kind, '', options[key], canonical, rank=rank))
        return rows
    if host in {'item.gmarket.co.kr', 'm.gmarket.co.kr', 'www.gmarket.co.kr'}:
        number = parameter('goodscode', 'gcode') if path.lower().rstrip('/') in {'/item', '/vi'} else ''
        if number:
            return found('gmarket', number, 'https://item.gmarket.co.kr/Item?goodscode=' + number,
                         variant=parameter('skuId', 'optionNo'))
    if host in {'itempage3.auction.co.kr', 'itempage.auction.co.kr', 'mobile.auction.co.kr'}:
        number = parameter('itemno', pattern=r'[a-zA-Z0-9]+') if path.lower().endswith('/detailview.aspx') else ''
        if number:
            return found('auction', number.upper(), 'https://itempage3.auction.co.kr/DetailView.aspx?itemno=' + number.upper())
    if host in {'11st.co.kr', 'www.11st.co.kr', 'm.11st.co.kr'}:
        match = re.fullmatch(r'/products/(?:[a-zA-Z]+/)?(\d+)/?', path)
        number = match[1] if match else parameter('prdNo') if 'product' in path.lower() else ''
        if number:
            return found('11st', number, 'https://www.11st.co.kr/products/' + number,
                         variant=parameter('optNo', 'optionNo'))
    if host in {'www.lotteon.com', 'lotteon.com', 'm.lotteon.com'}:
        match = re.fullmatch(r'/p/product/([a-zA-Z0-9]+)/?', path)
        if match:
            return found('lotteon', match[1], 'https://www.lotteon.com/p/product/' + match[1],
                         variant=parameter('sitmNo', pattern=r'[a-zA-Z0-9]+'))
    if host == 'store.kakao.com' and (match := re.fullmatch(r'/([^/]+)/products/(\d+)/?', path)):
        return found('kakao', match[2], f'https://store.kakao.com/{match[1]}/products/{match[2]}', match[1].lower())
    if host in {'ohou.se', 'www.ohou.se', 'store.ohou.se'}:
        match = re.fullmatch(r'/(goods|productions)/(\d+)(?:/selling)?/?', path)
        if match:
            return found('ohou.' + match[1], match[2], f'https://{host}/{match[1]}/{match[2]}')
    if host in {'www.aliexpress.com', 'ko.aliexpress.com', 'm.aliexpress.com', 'aliexpress.com'}:
        match = re.fullmatch(r'/item/(\d+)\.html', path)
        if match:
            return found('aliexpress', match[1], 'https://www.aliexpress.com/item/' + match[1] + '.html',
                         variant=parameter('sku_id', 'skuId'))
    if host in {'amazon.com', 'www.amazon.com', 'amazon.co.jp', 'www.amazon.co.jp', 'amazon.de', 'www.amazon.de'}:
        match = re.search(r'/(?:dp|gp/product)/([a-zA-Z0-9]{10})(?:/|$)', path)
        if match:
            market = host.removeprefix('www.')
            return found('amazon', match[1].upper(), f'https://www.{market}/dp/{match[1].upper()}', market)
    if host in {'www.ssg.com', 'm.ssg.com', 'www.emart.com', 'emart.ssg.com'} and path.lower().endswith('/itemview.ssg'):
        number = parameter('itemId')
        if number:
            return found('ssg', number, 'https://www.ssg.com/item/itemView.ssg?itemId=' + number)
    if host in {'www.musinsa.com', 'musinsa.com', 'm.musinsa.com'}:
        match = re.fullmatch(r'/(?:app/goods|products)/(\d+)/?', path)
        if match:
            return found('musinsa', match[1], 'https://www.musinsa.com/products/' + match[1])
    # Cafe24 product numbers are scoped to the storefront, never compared globally.
    number = parameter('product_no') if path.rstrip('/') == '/product/detail.html' else ''
    if not number and (match := re.fullmatch(r'/product/[^/]+/(\d+)(?:/.*)?', path)):
        number = match[1]
    if number:
        shop = host.removeprefix('www.')
        return found('storefront', number, f'https://{shop}/product/detail.html?product_no={number}', shop)
    return []


def preferred(rows):
    """An option-level identifier takes precedence over its multi-option listing."""
    highest = {}
    for row in rows:
        merchant = row['namespace'].split('.')[0], row['scope']
        highest[merchant] = max(highest.get(merchant, 0), row['rank'])
    return [row for row in rows if row['rank'] == highest[(row['namespace'].split('.')[0], row['scope'])]]


def needs_redirect(url):
    url = unwrap(url)
    return bool(url and urlsplit(url).hostname.lower() in SHORT_HOSTS and not extract(url))
