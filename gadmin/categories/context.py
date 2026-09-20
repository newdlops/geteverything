"""Deterministic classification using title evidence and bounded source metadata.

Metadata is a fallback, not a training label. Broad or mixed source categories
are deliberately omitted. The fingerprint includes every input used here.
"""
import hashlib
import json
import re
from urllib.parse import urlsplit

from . import rules


SOURCE_CATEGORIES = {
    '먹거리': 'food', '식품': 'food',
    'SW/게임': 'games', '게임': 'games.game',
    'PC관련': 'computer', 'PC제품': 'computer', 'PC/하드웨어': 'computer', '컴퓨터': 'computer',
    '의류/잡화': 'fashion', '의류잡화': 'fashion', '의류': 'fashion',
    '패션국내': 'fashion', '패션해외': 'fashion',
    '생활용품': 'home', '가전제품': 'electronics', '가전': 'electronics', '모바일': 'mobile',
    '화장품': 'beauty.cosmetic', '상품권/쿠폰': 'services.voucher',
    '서적': 'culture.books',
}
SITES = {'FMKOREA', 'PPOMPPU', 'ARCA', 'coolnjoy', 'EOMISAE'}
HOSTS = {
    'store.steampowered.com': 'games', 'store.epicgames.com': 'games.game',
    'www.gog.com': 'games', 'gog.com': 'games',
    'apps.apple.com': 'games', 'play.google.com': 'games',
    'flight.naver.com': 'services.travel',
}
SHOPS = {
    '스팀': 'games', 'steam': 'games', '에픽게임즈': 'games.game', '에픽': 'games.game',
    'gog': 'games.game', '스토브': 'games', '구글플레이': 'games',
    '구글플레이스토어': 'games', '플레이스토어': 'games', '앱스토어': 'games', 'ios': 'games',
    '네이버항공권': 'services.travel',
    '리디': 'culture.books', '네이버시리즈': 'culture.books', '알라딘': 'culture.books',
    '교보문고': 'culture.books', '예스24': 'culture.books',
    '유비소프트': 'games', '디즈니플러스': 'games.software', '넷플릭스': 'games.software',
    '애플tv': 'culture.video', 'apple tv': 'culture.video', '티빙': 'games.software',
}
BENEFITS = [
    ('services.membership', re.compile(r'네이버\s*(?:플러스\s*)?멤버[십쉽]')),
    ('services.points', re.compile(r'(?:포인트|적립|캐시백|페이백|스마일\s*복권|스마일캐[시쉬]|랜덤\s*캐[시쉬]|출석\s*체크|쌀먹)|(?:네이버|토스|카카오|페이코).{0,15}\d+\s*p\b|네페\s*\d+\s*원\s*지급|주유.{0,25}환급')),
    ('services.coupon', re.compile(r'쿠폰|할인\s*코드|장보기\s*지원금|간식\s*지원금|첫구매.{0,20}할인|배달.{0,15}할인|(?:요기요|땡겨요|배달의민족|주유|주유소|gs칼텍스|gs25|이디야).{0,30}할인')),
    ('services.event', re.compile(r'응모|경품|이모티콘|채널\s*추가|룰렛|뽑기|복권|럭키박스|즉석\s*당첨|네페\s*쏜다')),
    ('services.promotion', re.compile(r'세일|할인\s*행사|기획전|특가전|할인전|브랜드\s*(?:위크|데이)|할인\s*대전|최대\s*\d+\s*%\s*할인|전품목.{0,15}할인|t데이|결제\s*혜택|멤버십\s*데이|고객\s*(?:감사|보답)|보답\s*프로그램|신규가입\s*\d+원딜|(?:결제|구매)\s*시.{0,15}할인|전제품\s*할인')),
]


def host(url):
    try:
        return (urlsplit(url or '').hostname or '').casefold()
    except ValueError:
        return ''


def inputs(deal):
    return {'site': deal.community_name, 'original_category': deal.category,
            'shop_name': deal.shop_name, 'shop_urls': (deal.shop_url_1, deal.shop_url_2)}


def fingerprint(title, **metadata):
    value = [rules.normalize(title), metadata.get('site') or '', metadata.get('original_category') or '',
             rules.normalize(metadata.get('shop_name')), [host(url) for url in metadata.get('shop_urls', ())]]
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def classify(title, *, site='', original_category='', shop_name='', shop_urls=()):
    decision = rules.classify(title)
    if decision.category or decision.reason in ('unavailable_title', 'conflicting_products'):
        return decision
    text = rules.normalize(title)
    # A payment/discount notice remains a benefit even on a food/game board.
    if re.search(r'(?:땡겨요|요기요|배달의민족|배민).{0,30}할인|(?:결제\s*시|콘텐츠페이|선착순\s*쿠폰)', text):
        for category, pattern in BENEFITS:
            if category in ('services.points', 'services.coupon') and (match := pattern.search(text)):
                return rules.Decision(category, 'benefit:' + match.group())
        if '할인' in text:
            return rules.Decision('services.coupon', 'benefit:결제 할인')
    if original_category == '상품권/쿠폰' and '쿠폰' in text:
        return rules.Decision('services.coupon', 'benefit:쿠폰')
    for url in shop_urls:
        hostname = host(url)
        if hostname in HOSTS:
            return rules.Decision(HOSTS[hostname], 'shop_host:' + hostname)
    shop = rules.normalize(shop_name)
    if shop in SHOPS:
        return rules.Decision(SHOPS[shop], 'shop_name:' + shop)
    if re.search(r'(?:만원|천원|프로|%)', text) and shop == '온누리':
        return rules.Decision('services.voucher', 'shop_name:온누리')
    if decision.reason == 'no_clear_product' and original_category in ('세일정보','이벤트','응모') and re.search(r'할인|반값|특가|데이|결제', text):
        return rules.Decision('services.promotion', 'source_promotion:' + original_category)
    # In mixed food/health boards, dosage is health evidence; ordinary food
    # quantities are useful only alongside that board, never on their own.
    if site in SITES and original_category in ('식품/건강', '먹거리', '식품'):
        if re.search(r'\d+\s*(?:mg|캡슐|정\b|일분|개월분)|건강기능식품|보충제', text):
            return rules.Decision('beauty.supplement', 'source_dosage:' + original_category)
        if original_category == '식품/건강' and re.search(r'\d+\s*(?:kg|g|ml|캔|봉|미|병|포|팩|입)|국내산|국산|수제|[가-힣]+맛', text):
            if not re.search(r'건강|제약|뉴트리|영양|비타|진액|프로틴|단백|칼마|이뮨|\biso\b|파우더|오일', text):
                return rules.Decision('food', 'source_food_quantity:' + original_category)
    if site in SITES and (original_category or '').strip() in SOURCE_CATEGORIES:
        category = (original_category or '').strip()
        return rules.Decision(SOURCE_CATEGORIES[category], f'source_category:{site}/{category}')
    for category, pattern in BENEFITS:
        match = pattern.search(text)
        if match:
            return rules.Decision(category, 'benefit:' + match.group())
    return decision
