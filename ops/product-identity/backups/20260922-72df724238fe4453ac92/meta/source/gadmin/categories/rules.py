"""Conservative product rules. Source-site categories are not training labels."""
from dataclasses import dataclass
import hashlib
import html
import re
import unicodedata
from . import vocabulary

VERSION = 'rules-4'


@dataclass(frozen=True)
class Decision:
    category: str = ''
    reason: str = 'no_clear_product'


def normalize(title):
    text = unicodedata.normalize('NFKC', html.unescape(title or '')).casefold()
    text = re.sub(r'[\u200b-\u200f\ufeff]', '', text)
    text = re.sub(r'^\s*(?:\[(?:네이버(?:쇼핑)?|쿠팡|g마켓|옥션|알리|11번가|컴퓨존|롯데온|기타|카카오톡딜|카카오쇼핑|홈플러스)\]\s*)+', '', text)
    text = re.sub(r'\([^()]*(?:[\d,]+원|무배|무료배송)[^()]*\)', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()[:512]


def title_hash(title):
    return hashlib.sha256(normalize(title).encode()).hexdigest()


# These describe the product itself and override embedded brand/device names.
SPECIAL = [
    ('home.cleaning', r'(?:로봇\s*청소기|건조기).{0,12}(?:세제|세정제|유연제|시트)|신발\s*클리너'),
    ('sports.outdoor', r'캠핑\s*(?:의자|체어|테이블)'),
    ('beauty.health', r'(?:스팀|온열|수면)\s*안대'),
    ('home.hygiene', r'물티슈'),
    ('electronics.cleaning', r'망고비데'),
    ('pet.food', r'(?:고양이|강아지|반려견|반려묘|포켄스).{0,25}(?:덴탈|양치껌|덴티)'),
    ('auto.accessory', r'차량.{0,15}(?:거치대|충전|성에|커버)|차량용\s*방향제'),
    ('auto.care', r'워셔액|와이퍼|엔진\s*오일|연료\s*첨가제|불스원샷|타이어\s*(?:공기|주입)|세차\s*(?:용|타월|샴푸)|자동차\s*물왁스'),
    ('auto.device', r'블랙박스|하이패스\s*단말기'),
    ('electronics.beauty', r'헤어\s*드라이[어기]|헤어\s*스타일러'),
    ('home.kitchen', r'(?:냉동밥|밥|반찬).{0,5}(?:보관)?용기|(?:정수|브리타).{0,25}필터'),
    ('mobile.accessory', r'터치펜|애플\s*펜슬|(?:레노버|아이패드).{0,15}펜슬'),
    ('pet.food', r'하림펫푸드|로얄캐닌|퓨리나'),
    ('food.drink', r'그린덴마크'),
    ('services.voucher', r'^(?!.*[+])(?!.*(?:구매|사면|결제|골라담기|\s외\s)).{0,35}(?:상품권|금액권|교환권|기프트\s*카드|\d\s*[천만]원권)'),
    ('services.telecom', r'요금제|알뜰폰'),
    ('baby.care', r'기저귀'),
    ('home.cleaning', r'식기세척기.{0,12}(?:세제|세정제)|(?:액상|캡슐|세탁)\s*세제|건조기\s*시트'),
    ('fashion.accessory', r'쿠션.{0,12}양말'),
    ('beauty.supplement', r'웨이\s*프로틴|단백질\s*보충제|멀티\s*비타민.{0,12}태블릿'),
    ('electronics.kitchen', r'김치\s*냉장고|커피\s*(?:머신|메이커)'),
    ('electronics.audio', r'모니터\s*스피커(?!\s*내장)'),
    ('computer.monitor', r'스마트\s*모니터|모니터.{0,25}스피커\s*내장|스피커\s*내장.{0,25}모니터'),
    ('computer.peripheral', r'식빵\s*키보드'),
    ('beauty.health', r'스마트\s*체중계'),
    ('pet.food', r'(강아지|고양이|반려견|반려묘).*(사료|화식|간식)|(?:사료|강아지화식)'),
    ('pet.supplies', r'(강아지|고양이|반려견|반려묘).*(방석|침대|쿠션|장난감|모래|하네스)'),
    ('home.cleaning', r'식기세척기\s*세제'),
    ('home.furniture', r'게이밍\s*의자|모션\s*데스크|메쉬\s*의자|tv\s*스탠드'),
    ('computer.peripheral', r'마우스\s*패드|모니터\s*(?:암|조명|받침대|거치대)|스크린\s*바|키\s*캡'),
    ('mobile.accessory', r'(아이폰|갤럭시|휴대폰|스마트폰|아이패드).{0,24}(케이스|보호\s*필름)|맥세이프|보조\s*배터리|(?:충전|usb).{0,15}케이블|(?:고속\s*)?충전기'),
    ('computer.laptop', r'노트북|갤럭시\s*북|맥북|비보북|씽크패드|니트로\s*(?:16|17|v\s*1[56])|expertbook|thinkpad|vivobook|laptop'),
    ('computer.desktop', r'완본체|조립\s*(pc|컴퓨터)|데스크[톱탑]'),
]

PATTERNS = {
    'computer.monitor': r'모니터(?!링)|\b[124][0-9]{2}\s*hz\b|\b(?:wqhd|uwqhd)\b',
    'computer.component': r'그래픽\s*카드|메인\s*보드|파워\s*서플라이|cpu\s*쿨러|\b(?:ddr[345]|ram|rtx\s*[2345]\d{3}|rx\s*[679]\d{3}|라이젠|ryzen)\b|80\s*plus',
    'computer.storage': r'\b(?:ssd|hdd|nvme)\b|외장\s*하드|씨게이트|바라쿠다|마이크로\s*sd',
    'computer.peripheral': r'키보드|마우스|복합기|프린터|멀티포트\s*허브|공유기',
    'mobile.phone': r'아이폰\s*\d|갤럭시\s*(?:s\s*\d|z\s*(?:폴드|플립))|스마트폰',
    'mobile.tablet': r'아이패드|갤럭시\s*탭|태블릿|아이노트|ainote',
    'mobile.wearable': r'스마트\s*워치|애플\s*워치|갤럭시\s*워치',
    'electronics.audio': r'이어폰|헤드[셋폰]|스피커|사운드\s*바|에어팟|갤럭시\s*버즈|프리소너스',
    'electronics.tv': r'\btv\b|텔레비전|삼탠바이미',
    'electronics.cleaning': r'(?:무선|로봇|진공)\s*청소기|세탁기|건조기|(?<!마이)비데',
    'electronics.kitchen': r'커피\s*머신|에어\s*프라이어|전자레인지|냉장고|밥솥|식기세척기',
    'electronics.climate': r'에어컨|공기\s*청정기|가습기|제습기|선풍기|전기\s*장판',
    'electronics.beauty': r'드라이[어기]|고데기|(?:전기|전동)\s*면도기',
    'games.console': r'게임\s*패드|컨트롤러|닌텐도.*본체|플레이스테이션\s*5\s*(?:본체|프로)|스팀덱',
    'games': r'닌텐도|플레이스테이션|스팀\s*(?:게임|주간할인)',
    'games.game': r'사이버펑크|바이오하자드|바이오쇼크|역전재판|스플릿\s*픽션|붉은\s*사막|the witcher|grand theft auto|battlefield|dying light|\[스팀\]',
    'games.software': r'듀오링고|마이크로소프트\s*365|오피스\s*365|윈도우\s*(?:10|11)|백신\s*라이선스',
    'food.fresh': r'삼겹|목살|우삼겹|앞다리살|닭다리|생닭|닭가슴살|부채살|등심|양파|고등어|곶감|고구마|한라봉|천혜향|레드향|단감|오렌지(?!\s*(?:맛|향))|골드키위|토마토|깐마늘|(?:못난이|부사|홍로).{0,8}사과|사과(?=\s|\d|$)|당근\s*\d|새조개|대패\s*삼겹|구운\s*계란|망고|칵테일새우|새우살|냉동새우|닭안심|안창살|바나나|양배추|감자(?=\s|\d|$)',
    'food.prepared': r'돈[까가]스|떡갈비|떡볶이|라면|짜파게티|신라면|안성탕면|짜슐랭|간짬뽕|비빔면|김치|장조림|즉석\s*밥|햇반|현미밥|주먹밥|교자|만두|치킨|닭갈비|불고기|우동|피자|비엔나|소[시세]지|천하장사|스팸|크래미|어묵|도시락|해장국|도가니탕|사골|참치.*(?:캔|살코기)|된장국|두루치기|편육|버거|가래떡|육개장|설렁탕|갈비탕|볶음밥|양념갈비|la\s*갈비|너겟|텐더스틱|짜장면|비빔국수|냉면|유부초밥|삼계탕',
    'food.snack': r'허니버터칩|초코(?:칩|볼|바|파이)|초콜릿|과자|건빵|다이제|나샌드|아이스크림|구구크러스트|월드콘|페레로|젤리|호빵|고래밥|콘칩|콘칲|사브레|비스킷|쿠크다스|크래커|캔디|새콤달콤|그래놀라|단팥|소보로|호떡|땅콩빵|보리건빵|찰떡파이|치킨팝|프링글스|오예스|빈츠|비쵸비|맛동산|새우깡|칸쵸|롯데샌드|빠다코코낫|몽쉘|나뚜루|하겐다즈|시리얼|후레이크|첵스|오레오|소금빵|기린빵|단팥빵|모닝빵|식빵|크루아상|베이글|스크류바|돼지바|와일드바디',
    'food.drink': r'콜라(?!겐|보)|펩시|사이다|탄산수|생수|먹는\s*샘물|삼다수|코카콜라|스프라이트|마운틴듀|파워에이드|레쓰비|커피(?!\s*머신)(?:믹스)?|아메리카노|몬스터\s*에너지|몬스터에너지|핫식스|닥터페퍼|포카리|하늘보리|주스|우유|갈아만든\s*배|말차에몽|야[쿠구]르트|요구르트|카스제로|밀키스|오랑지나|웰치스|데미소다|오라떼|토레타|초록매실|옥수수수염차|보리차|두유|환타|트레비',
    'food.pantry': r'찹쌀|햅쌀|새청무|쌀\s*\d|올리브유|스파게티\s*소스|파스타\s*소스|버터\s*(?:가염|무염)|야생화꿀|크림치즈|부침가루',
    'home.cleaning': r'세제|섬유\s*유연제|세정제|섬유\s*탈취제|청소포|청소티슈|테이프\s*크리너|테이프\s*클리너',
    'home.hygiene': r'화장지|키친\s*타[월올]|미용\s*티슈|롤\s*티슈|치약|칫솔|리스테린|면도날|핸드\s*워시|마이비데',
    'home.kitchen': r'프라이팬|후라이팬|냄비|주방수전|야채칼|식도|벌집\s*웍|텀블러|보온병',
    'home.furniture': r'책상|소파|매트리스|베개|이불|(?<!받)침대|의자|쿠션',
    'home.supplies': r'건전지|인센스|디퓨저|멀티탭',
    'fashion.clothing': r'자[켓킷]|재킷|패딩|파카|코트|맨투맨|티셔츠|슬리브티|슬랙스|팬츠|드로즈|팬티|빤스|트렁크|스웨터|셔츠|저고리|(?<![가-힣a-z])니트(?!로)|캐시미어\s*니트|후디|바람막이|골프웨어|트레이닝\s*셋업|긴팔\s*저지',
    'fashion.shoes': r'운동화|러닝화|트레킹화|부츠|샌들|슬리퍼|반스\s*어센틱|닥터마틴',
    'fashion.accessory': r'머플러|볼캡|메신저백|백팩|팔찌|바라클라바|반다나|목토시|장갑|선글라스|아이웨어|양말',
    'fashion': r'유니클로|무신사|무탠다드|무인양품.*(?:의류|심리스)|폴로\s*랄프로렌|파타고니아|그라미치|칼하트|아디제로|뉴발란스|나이키\s*acg|플랙진',
    'beauty.supplement': r'비타민|오메가\s*3|루테인|지아진틴|아스타잔틴|영양제|락토핏|코큐텐|coq10|웨이\s*프로틴|프로틴\s*(?:파우더|쉐이크)|단백질\s*쉐이크|유산균|침향환',
    'beauty.care': r'샴푸|바디\s*워시|헤어\s*(?:세럼|퍼퓸|테라피)|트리트먼트',
    'beauty.cosmetic': r'향수|스킨\s*케어|선크림|크림\s*인\s*젤|랩핑팩|마스크\s*팩|퍼퓸',
    'beauty.health': r'체온계|혈압계|콘돔|마데카솔|연고|메디패치',
    'baby.care': r'기저귀|젖병|유모차|아기\s*띠|아기띠',
    'baby.food': r'분유|이유식',
    'sports.outdoor': r'텐트|침낭|캠핑\s*(?:의자|테이블)|낚싯대',
    'sports.fitness': r'덤벨|아령|요가\s*매트|폼롤러|러닝머신',
    'sports.hobby': r'건담|프라모델|피규어|레고|보드\s*게임|인형',
    'services.voucher': r'상품권|기프트\s*카드|기프티콘|교환권|금액권',
    'services.travel': r'(?:호텔|리조트).{0,20}(?:숙박|\d박|객실|조식)|비발디파크|객실\s*1박|항공권|입장권|숙박권',
    'services.telecom': r'알뜰폰|요금제|유심\s*개통',
}
SPECIAL = [(code, re.compile(pattern)) for code, pattern in SPECIAL]
PATTERNS['fashion.clothing'] = PATTERNS['fashion.clothing'].replace('후디|', '후디(?!스)|')
PATTERNS = [(code, re.compile(pattern)) for code, pattern in PATTERNS.items()]


def classify(title):
    return _classify(normalize(title))


def _classify(text, check_bundle=True):
    if not text or re.search(r'전체\s*공개로\s*전환|권한이\s*없|로그인.*필요|^list_(?:ad_link|adsense)$|광고\s*계정으로\s*확인되어\s*차단|^추가\s*배송비$|^상품명과\s*구성품|^배송비\s*체험딜\s*상품\s*다양$', text):
        return Decision(reason='unavailable_title')
    # Remove clearly marked gifts, retaining product names, model numbers and sizes.
    text = re.sub(r'\[[^\[\]]{0,40}(?:증정|사은품)[^\[\]]{0,10}\]', '', text)
    text = re.sub(r'\s*[+,]\s*[^+,]*(?:증정|사은품).*$', '', text)
    text = re.sub(r'노트북\s*(?:용\s*)?(?=보조\s*배터리)', '', text)
    text = re.sub(r'[+]\s*(?:선물)?쇼핑백(?:\s*증정)?', '', text)
    text = re.sub(r'닭터의자연', '닭터자연', text)
    text = text.replace('원양산', '원양어획')
    if check_bundle:
        # A quantified food pack with a branded cup/keyring is a food offer.
        # Resolve the main item before dropping the explicitly named companion.
        bundle = re.match(r'(.+?)(?:\s*\+\s*)(?:그린\s*|랜덤\s*|미니\s*|아크릴\s*|rb\s*|치오\s*)?(?:머그|키링|에코백|토트백|버킷햇|텀블러|달력|핫팩|룸스프레이|쇼핑백|볼펜)', text)
        if bundle and re.search(r'\d+\s*(?:캔|팩|입|개|봉|병|박스|box|p\b|t\b)', bundle[1]):
            main = _classify(bundle[1], check_bundle=False)
            if main.category.startswith('food'):
                return Decision(main.category, 'main_product:' + main.reason[:150])
        bundle = re.match(r'(.+?)\s*\+\s*(?:붉은\s*사막|바이오하자드|세정제|충전\s*케이블)', text)
        if bundle:
            main = _classify(bundle[1], check_bundle=False)
            if main.category.startswith('computer') or main.category == 'electronics.cleaning':
                return Decision(main.category, 'main_product:' + main.reason[:150])
    # A spaced separator denotes independent products. Bare '+' also occurs in
    # brands (U+), model suffixes (SE+), quantities (1+1), and ingredient names.
    if check_bundle and re.search(r'\s\+\s', text):
        segments = [part for part in re.split(r'\s+\+\s+', text) if part.strip()]
        parts = [_classify(part, check_bundle=False) for part in segments]
        if len({part.category.split('.')[0] for part in parts if part.category}) > 1:
            return Decision(reason='conflicting_products')
    companion = re.match(r'(.+\d+\s*(?:팩|입|봉|캔|병|마리))\s*\+\s*(?:수저세트|머그컵|키링)', text)
    if companion and not _classify(companion[1], check_bundle=False).category:
        return Decision(reason='no_clear_product')
    # Compound product nouns outrank a flavour, a compatible device or a gift.
    for code, pattern in PRIMARY:
        match = pattern.search(text)
        if match:
            return Decision(code, 'product:' + match.group()[:100])
    special = [(code, pattern.search(text)) for code, pattern in SPECIAL]
    special = [(code, match) for code, match in special if match]
    if special:
        roots = {code.split('.')[0] for code, _ in special}
        if len(roots) > 1:
            return Decision(reason='conflicting_products')
        code, match = special[0]
        return Decision(code, 'product:' + match.group()[:80])
    found = [(code, pattern.search(text)) for code, pattern in PATTERNS]
    found = [(code, match) for code, match in found if match]
    # Expand uncovered titles without replacing a resolved product with a brand.
    if not found:
        found = vocabulary.matches(text)
    if not found:
        found = vocabulary.matches(text, brands=True)
    roots = {code.split('.')[0] for code, _ in found}
    if len(roots) != 1:
        return Decision(reason='conflicting_products' if roots else 'no_clear_product')
    codes = {code for code, _ in found if '.' in code}
    code = next(iter(codes)) if len(codes) == 1 else next(iter(roots))
    return Decision(code, 'product:' + ','.join(match.group()[:30] for _, match in found)[:150])


PRIMARY = [(code, re.compile(pattern)) for code, pattern in [
    ('electronics.climate', r'전기\s*담요|히팅\s*패드'),
    ('fashion.clothing', r'숏\s*슬리브|와플.{0,10}(?:맨즈|메쉬|폴로)|(?<![가-힣])반팔'),
    ('fashion.accessory', r'캡\s*모자'),
    ('home.furniture', r'폴라\s*데스크'),
    ('food.pantry', r'불닭\s*(?:소스|마요소스)'),
    ('food.drink', r'쿨피스'),
    ('beauty.health', r'듀오덤'),
    ('fashion.shoes', r'초등\s*실내화'),
    ('mobile.accessory', r'보조\s*배터리|맥세이프|(?:아이폰|갤럭시|아이패드).{0,16}(?:케이스|필름)|터치펜'),
    ('computer.peripheral', r'모니터\s*(?:암|받침대|조명)|스크린바'),
    ('home.furniture', r'tv\s*(?:스탠드|거치대)'),
    ('electronics.audio', r'모니터\s*스피커(?!\s*내장)'),
    ('fashion.accessory', r'여행용\s*캐리어'),
    ('electronics.beauty', r'바디\s*트리머'),
    ('home.cleaning', r'고농축\s*피죤'),
    ('home.kitchen', r'(?:소금|후추)\s*그라인더|젖병\s*세척솔'),
    ('food.drink', r'홍삼차|(?:애사비|탄산)\s*(?:소다|음료)'),
    ('electronics.kitchen', r'계란\s*찜기|에그\s*쿠커|광파\s*오븐'),
    ('electronics.climate', r'실링\s*팬|실링팬|에어컨'),
    ('computer.peripheral', r'웹캠|웹\s*캠|화상\s*카메라'),
    ('fashion.accessory', r'브라이튼\s*본드'),
    ('fashion.shoes', r'청키\s*리프트\s*스니커즈'),
    ('home.hygiene', r'미용\s*티슈|면도날\s*세트'),
    ('home.supplies', r'리빙\s*박스'),
    ('food.pantry', r'코인\s*육수|진한\s*육수'),
    ('food.snack', r'(?:cgv|메가박스).{0,15}(?:팝콘|스몰세트)|트윅스\s*탑\s*스니커즈|빼빼로\s*캐리어'),
    ('electronics.cleaning', r'코드제로.{0,20}청소기'),
    ('electronics.audio', r'헤드[폰셋].{0,20}(?:정수리\s*커버|헤드\s*밴드)'),
    ('culture.books', r'웹툰|단행본'),
    ('mobile.tablet', r'이북\s*리더기|전자책\s*리더'),
    ('electronics.camera', r'홈캠'),
    ('computer.storage', r'네트워크\s*스토리지|나스\s*서버'),
    ('electronics.audio', r'게이밍\s*헤드셋|게이밍\s*이어폰'),
    ('home.hygiene', r'쉐이브\s*가드|교정기\s*세정제'),
    ('beauty.care', r'바디\s*로션|핸드\s*크림'),
    ('beauty.supplement', r'비타프레쉬|비타민c&d|레몬\s*효소'),
    ('food.drink', r'숙취해소\s*음료'),
    ('home.kitchen', r'인덕션\s*압력솥'),
    ('food.snack', r'호올스\s*스틱|견과\s*골라먹는'),
    ('games.console', r'레트로\s*게임기'),
    ('games.game', r'사이버펑크'),
    ('computer.peripheral', r'독거미\s*f\d'),
    ('auto.care', r'타이어.{0,20}공기\s*주입기'),
    ('food.pantry', r'칼슘\s*치즈|고칼슘치즈'),
    ('home.kitchen', r'가마솥.{0,15}인덕션'),
    ('computer.storage', r'nvme|\bssd\b'),
    ('fashion.shoes', r'에어포스(?!\s*(?:군용|공기))'),
    ('services.voucher', r'케이크\s*할인권|컬처패스'),
    ('home.supplies', r'충전식\s*손난로'),
    ('electronics.tool', r'에어건'),
    ('home.lighting', r'빔프로젝터.{0,12}무드등'),
    ('home.kitchen', r'야채\s*탈수기'),
    ('beauty.care', r'발을씻자'),
    ('sports.hobby', r'오페라글라스|콘서트\s*망원경'),
    ('food.drink', r'에너지\s*드링크|비타500'),
    ('electronics.tv', r'무빙스타일.{0,12}티비'),
    ('electronics.beauty', r'갈바닉'),
    ('electronics.tool', r'충전식\s*무선\s*드라이버'),
    ('home.kitchen', r'파스타\s*보울'),
    ('home.supplies', r'사쉐\s*방향제'),
    ('fashion.shoes', r'나이키\s*에어포스'),
    ('services.voucher', r'식사권'),
    ('pet.food', r'하루양갱|밥이보약|(?:강아지|고양이).{0,30}(?:사료|간식)'),
    ('pet.supplies', r'애견용품|펫전용|고양이\s*용품'),
    ('food.drink', r'비타민.{0,12}(?:멸균우유|두유)|(?:칼슘|비타민d).{0,12}두유|콤부차'),
    ('beauty.supplement', r'프로틴\s*(?:파우더|아이솔레이트)|신타\s*-?\s*6|\bbpi\s*iso|유산균|종합\s*비타민|멜라토닌'),
    ('home.hygiene', r'구강\s*청결제|치약|칫솔(?!\s*살균)'),
    ('home.cleaning', r'주방\s*세제|섬유\s*유연제|울샴푸|이염방지'),
    ('home.kitchen', r'쌀통|반찬통|텀블러\s*컵|인덕션.{0,20}(?:팬\d|프라이팬|후라이팬|냄비)'),
    ('home.furniture', r'바지\s*옷걸이'),
    ('home.supplies', r'인센스|접이식\s*카트'),
    ('home.lighting', r'오르골\s*무드등'),
    ('beauty.cosmetic', r'앰플|세럼|에센스(?!\s*쿡)|재생\s*크림|팩클렌저'),
    ('beauty.health', r'야돔|습윤\s*밴드|ems.{0,15}마사지기'),
    ('fashion.accessory', r'스마트폰.{0,10}(?:니트)?\s*장갑|쿼츠\s*시계|손목\s*시계'),
    ('fashion.shoes', r'쿠션.{0,20}(?:운동화|슬리퍼|트레킹화|스니커즈)'),
    ('fashion.clothing', r'떡볶이\s*코트|건빵\s*조거팬츠|와플\s*폴로|스프라이트\s*(?:와플|머플러)'),
    ('games.console', r'게임\s*패드|컨트롤러|8bitdo'),
    ('games.software', r'(?:디즈니\s*플러스|밀리의\s*서재|윌라).{0,20}구독권'),
    ('computer.laptop', r'노트북(?!\s*(?:용|보조배터리))|게이밍\s*노트|젠북|비보북'),
    ('computer.peripheral', r'팜레스트|유무선.{0,10}키보드|버티컬\s*마우스|매직\s*키보드'),
    ('computer.monitor', r'모니터(?!암|\s*암|\s*스탠드|\s*링)|울트라기어'),
    ('electronics.tv', r'(?<![a-z])tv\b|스마트tv|비즈니스tv|이동식tv'),
    ('electronics.kitchen', r'지니오\s*s|캡슐\s*머신|냉장고|김치톡톡'),
    ('food.prepared', r'에어\s*프라이어.{0,20}(?:돈까스|치킨)|전자레인지.{0,15}고등어'),
    ('electronics.cleaning', r'(?<!마이)비데|(?:물걸레|침구|스팀).{0,8}청소기|세제자동투입'),
    ('electronics.beauty', r'전기\s*면도기|전동\s*면도기'),
    ('electronics.tool', r'전동\s*드릴|충전\s*드릴'),
    ('sports.outdoor', r'캠핑\s*화로대'),
    ('services.voucher', r'기프티콘|교환권|금액권|상품권|바우처'),
    ('services.travel', r'레고랜드|관람권|입장권|이용권|시즌권|리프트권'),
    ('home.hygiene', r'물티슈|핸드\s*(?:워시|솝)|손\s*세정제'),
    ('home.cleaning', r'(?:로봇\s*청소기|건조기).{0,12}(?:세제|세정제|유연제|시트)'),
    ('auto.accessory', r'차량용.{0,20}(?:충전기|거치대)|자동차\s*필터|카매트'),
    ('baby.care', r'분유\s*포트|아기\s*베개|두상\s*베개'),
    ('beauty.care', r'바디\s*워시|헤어\s*스프레이|염색약'),
    ('beauty.cosmetic', r'향수|클렌징|선크림|썬크림'),
    ('beauty.supplement', r'(?<!하)이뮨|정관장|산양산삼|웨이\s*프로틴|분리대두단백질'),
    ('electronics.cleaning', r'스타일러|망고비데'),
    ('electronics.beauty', r'헤어\s*드라이[어기]|헤어\s*스타일러'),
]]
