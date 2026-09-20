import unittest

from gadmin.categories import context, taxonomy


class ContextRulesTests(unittest.TestCase):
    def test_fallbacks_keep_auditable_evidence_and_conservative_parents(self):
        cases = [
            ('R.E.P.O.', {'shop_urls': ['https://store.steampowered.com/app/123']}, 'games', 'shop_host:'),
            ('낯선 게임 타이틀', {'site': 'ARCA', 'original_category': 'SW/게임'}, 'games', 'source_category:'),
            ('인천다카마쓰 0426 0430', {'shop_name': '네이버항공권  '}, 'services.travel', 'shop_name:'),
            ('지리산수 2L 18병', {'site': 'PPOMPPU', 'original_category': '식품/건강'}, 'food', 'source_food_quantity:'),
            ('전립선 건강기능식품 60캡슐', {'site': 'PPOMPPU', 'original_category': '식품/건강'}, 'beauty.supplement', 'source_dosage:'),
        ]
        for title, metadata, category, reason in cases:
            with self.subTest(title=title):
                result = context.classify(title, **metadata)
                self.assertEqual(result.category, category)
                self.assertTrue(result.reason.startswith(reason))
                self.assertIn(result.category, taxonomy.LABELS)

    def test_mixed_source_categories_and_unknown_hosts_are_not_guesses(self):
        for metadata in ({'site': 'PPOMPPU', 'original_category': '기타'},
                         {'site': 'PPOMPPU', 'original_category': '가전/가구'},
                         {'site': 'untrusted', 'original_category': '먹거리'},
                         {'shop_urls': ['https://store.steampowered.com.example.org/app/123']},
                         {'shop_urls': ['https://[malformed']}):
            self.assertFalse(context.classify('알 수 없는 모델 ZX42', **metadata).category)
        self.assertFalse(context.classify('무명의 상품 500ml').category)

    def test_title_wins_over_misfiled_board_and_metadata_cannot_restore_bad_titles(self):
        self.assertEqual(context.classify('쿡스나이프', site='PPOMPPU', original_category='의류/잡화').category, 'home.kitchen')
        for title, site, board, expected in [
            ('하다라보 고쿠쥰 리프팅 3종', 'PPOMPPU', '의류/잡화', 'beauty.cosmetic'),
            ('레노버샤오신 Pad pro 12.7 2025 8+256GB', 'coolnjoy', 'PC관련', 'mobile.tablet'),
            ('디케이켈슨 무선 핸드 그라인더 풀세트', 'PPOMPPU', '의류/잡화', 'electronics'),
        ]:
            with self.subTest(title=title):
                self.assertEqual(context.classify(title, site=site, original_category=board).category, expected)
        self.assertFalse(context.classify('list_ad_link', site='ARCA', original_category='식품').category)
        self.assertFalse(context.classify('노트북 + 아이폰 케이스', site='ARCA', original_category='PC/하드웨어').category)
        self.assertFalse(context.classify('배송비 체험딜 상품 다양', site='FMKOREA', original_category='먹거리').category)

    def test_known_relationships_do_not_leak_accessories_flavours_or_promotions(self):
        cases = {
            '원양산 반건조 오징어 900g': 'food',
            '삼성 QLED TV 85인치 120Hz': 'electronics',
            '에어와플 메쉬 맨즈 숏슬리브': 'fashion',
            '캡모자 3개': 'fashion',
            '극세사 전기담요': 'electronics',
            '정관장 에브리타임 + 쇼핑백': 'beauty',
            '스타벅스 캡슐커피 50개 + 머그컵': 'food',
            'AMD 9800X3D + 붉은사막 게임코드': 'computer',
            '후디스 소화 편한 우유': 'food',
        }
        for title, root in cases.items():
            with self.subTest(title=title):
                self.assertEqual(context.classify(title).category.split('.')[0], root)
        self.assertFalse(context.classify('물티슈 + 구운란').category)
        self.assertEqual(context.classify('땡겨요 포장중복 2000원 할인', site='ARCA', original_category='식품').category, 'services.coupon')
        self.assertEqual(context.classify('KT콘텐츠페이 구글플레이 20% 할인', site='ARCA', original_category='SW/게임').category, 'services.coupon')

    def test_cache_fingerprint_includes_every_classification_input(self):
        base = {'site': 'ARCA', 'original_category': '식품', 'shop_name': '네이버', 'shop_urls': ['https://example.com/item']}
        for key, value in [('site', 'PPOMPPU'), ('original_category', '기타'), ('shop_name', '스팀'), ('shop_urls', ['https://store.steampowered.com/app/1'])]:
            self.assertNotEqual(context.fingerprint('같은 제목', **base), context.fingerprint('같은 제목', **{**base, key: value}))
        # Only hosts are used by the classifier, so tracking strings are irrelevant.
        self.assertEqual(context.fingerprint('같은 제목', **base), context.fingerprint('같은 제목', **{**base, 'shop_urls': ['https://example.com/item?utm_source=test']}))
