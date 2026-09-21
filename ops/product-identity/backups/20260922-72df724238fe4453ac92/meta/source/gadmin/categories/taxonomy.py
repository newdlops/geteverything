VERSION = '2026-09-19-v2'

# Codes are stable API values. A root is a valid result when a leaf is uncertain.
GROUPS = {
    'computer': ('PC·주변기기', {'desktop': '데스크톱', 'laptop': '노트북', 'monitor': '모니터', 'component': 'PC 부품', 'storage': '저장장치', 'peripheral': '주변기기'}),
    'mobile': ('모바일', {'phone': '휴대폰', 'tablet': '태블릿', 'wearable': '웨어러블', 'accessory': '모바일 액세서리'}),
    'electronics': ('가전·디지털', {'audio': '음향기기', 'tv': 'TV', 'cleaning': '청소·생활가전', 'kitchen': '주방가전', 'climate': '계절가전', 'beauty': '이미용가전', 'camera': '카메라·촬영기기', 'tool': '전동공구'}),
    'games': ('게임·소프트웨어', {'console': '게임기·컨트롤러', 'game': '게임', 'software': '소프트웨어·디지털 구독'}),
    'food': ('식품·음료', {'fresh': '신선식품', 'prepared': '가공·간편식', 'snack': '과자·디저트', 'drink': '음료·커피', 'pantry': '쌀·조미료·식재료'}),
    'home': ('생활·주방', {'cleaning': '세제·청소용품', 'hygiene': '위생용품', 'kitchen': '주방용품', 'furniture': '가구·침구', 'supplies': '생활잡화', 'garden': '꽃·원예', 'lighting': '조명'}),
    'fashion': ('패션·잡화', {'clothing': '의류', 'shoes': '신발', 'accessory': '가방·패션잡화'}),
    'beauty': ('뷰티·건강', {'cosmetic': '화장품·향수', 'care': '헤어·바디케어', 'supplement': '영양제', 'health': '건강용품'}),
    'baby': ('출산·육아', {'care': '육아용품', 'food': '분유·이유식'}),
    'pet': ('반려동물', {'food': '사료·간식', 'supplies': '반려동물용품'}),
    'sports': ('스포츠·레저·취미', {'outdoor': '캠핑·레저', 'fitness': '운동용품', 'hobby': '취미용품'}),
    'auto': ('자동차·차량용품', {'care': '차량 관리·정비', 'accessory': '차량 액세서리', 'device': '차량 전자기기'}),
    'culture': ('도서·문화', {'books': '도서·전자책', 'video': '영화·영상', 'music': '음반·음악'}),
    'services': ('상품권·혜택·서비스', {'voucher': '상품권·교환권', 'travel': '여행·숙박·티켓', 'telecom': '통신요금제', 'coupon': '할인쿠폰', 'points': '포인트·적립', 'event': '응모·증정 행사', 'promotion': '쇼핑 할인행사', 'membership': '멤버십·이용 서비스', 'education': '교육·강좌', 'finance': '금융·보험 혜택'}),
}
LABELS = {}
for root, (label, children) in GROUPS.items():
    LABELS[root] = label
    LABELS.update({root + '.' + code: label + ' > ' + name for code, name in children.items()})
CHOICES = [('', '미분류'), *LABELS.items()]


def describe(code):
    if code not in LABELS:
        return None
    root = code.split('.')[0]
    return {'code': code, 'label': LABELS[code], 'parent_code': root, 'parent_label': GROUPS[root][0]}
