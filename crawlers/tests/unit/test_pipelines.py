from copy import deepcopy
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from crawlers.arca.pipeline import ArcaPipeline
from crawlers.coolnjoy.item_pipeline import CoolNJoyPipeline
from crawlers.eomisae.pipeline import EomisaePipeline
from crawlers.fmkorea.pipeline import FmKoreaPipeline
from crawlers.ppomppu.pipeline import PpomppuPipeline
from gadmin.deals.models import Deal


COMMON_ITEM = {
    "article_id": "123",
    "origin_url": "https://example.com/deals/123",
    "shop_url_1": "https://shop.example.com/product/123",
    "shop_name": "쇼핑몰",
    "thumbnail": "https://example.com/thumbnail.jpg",
    "subject": "[쇼핑몰] 상품 (12,900원/무료)",
    "category": "식품",
    "recommend_count": "7",
    "dislike_count": "2",
    "view_count": "150",
    "delivery_price": "무료",
}
WRITE_AT = datetime(2025, 1, 2, 3, 4)


class PipelineTests(SimpleTestCase):
    def setUp(self):
        self.save = self.enterContext(patch.object(Deal, "save"))
        self.get_or_create = self.enterContext(patch.object(Deal.objects, "get_or_create"))
        self.update_or_create = self.enterContext(patch.object(Deal.objects, "update_or_create"))
        self.enterContext(patch("builtins.print"))

    def process(self, pipeline, *, overrides, prefix, defaults, updates, refresh_defaults=False):
        item = {**COMMON_ITEM, **overrides}
        original_item = deepcopy(item)
        existing_write_at = datetime(2024, 1, 1)
        deal = Deal(
            article_id=prefix + "123",
            subject="기존 제목",
            price=100,
            delivery_price=3000,
            write_at=existing_write_at,
            dislike_count=99,
        )
        manager_method = self.update_or_create if refresh_defaults else self.get_or_create
        manager_method.return_value = (deal, False)

        before = datetime.now()
        result = pipeline.process_item(item, spider=None)
        after = datetime.now()

        self.assertIs(result, item)
        self.assertEqual(item, original_item)
        manager_method.assert_called_once()
        call = manager_method.call_args.kwargs
        self.assertEqual(call["article_id"], prefix + "123")
        actual_defaults = dict(call["create_defaults"] if refresh_defaults else call["defaults"])
        if refresh_defaults:
            self.assertNotIn("thumbnail", call["defaults"])
        crawled_at = actual_defaults.pop("crawled_at")
        self.assertLessEqual(before, crawled_at)
        self.assertLessEqual(crawled_at, after)
        self.assertEqual(actual_defaults, defaults)

        for field, expected in updates.items():
            self.assertEqual(getattr(deal, field), expected, field)
        self.assertLessEqual(before, deal.update_at)
        self.assertLessEqual(deal.update_at, after)
        self.save.assert_called_once()
        written = self.save.call_args.kwargs["update_fields"]
        self.assertNotIn("thumbnail", written)
        self.assertEqual(set(written), {*updates, "shop_url_1", "numeric_evidence", "update_at"})
        self.assertEqual(deal.numeric_evidence['delivery'], str(item['delivery_price']))

        if refresh_defaults:
            self.get_or_create.assert_not_called()
        else:
            self.update_or_create.assert_not_called()
            self.assertEqual(deal.subject, "기존 제목")
            self.assertEqual(deal.price, 100)
            self.assertEqual(deal.write_at, existing_write_at)
        return deal

    def common_defaults(self):
        return {
            field: COMMON_ITEM[field]
            for field in ("shop_url_1", "shop_name", "thumbnail", "subject", "category")
        }

    def common_updates(self):
        return {
            field: COMMON_ITEM[field]
            for field in ("recommend_count", "dislike_count", "view_count")
        }

    def test_ppomppu_preserves_article_prefix_and_only_refreshes_counters_and_delivery(self):
        self.process(
            PpomppuPipeline(),
            overrides={"origin_url": "view.php?no=123", "write_at": "2025-01-02 03:04", "delivery_price": "2500"},
            prefix="ppompu",
            defaults={
                **self.common_defaults(),
                "origin_url": "https://www.ppomppu.co.kr/zboard/view.php?no=123",
                "write_at": WRITE_AT,
                "price": "12900",
                "community_name": "PPOMPPU",
            },
            updates={**self.common_updates(), "delivery_price": "2500"},
        )

    def test_fmkorea_refreshes_defaults_and_normalizes_delivery(self):
        self.process(
            FmKoreaPipeline(),
            overrides={"create_at": "2025.01.02 03:04", "delivery_price": "2500원"},
            prefix="fm",
            defaults={
                **self.common_defaults(),
                "origin_url": COMMON_ITEM["origin_url"],
                "create_at": WRITE_AT,
                "write_at": WRITE_AT,
                "price": "12900",
            },
            updates={**self.common_updates(), "delivery_price": 2500, "community_name": "FMKOREA"},
            refresh_defaults=True,
        )

    def test_arca_preserves_utc_currency_and_creation_only_delivery(self):
        for price, expected_price, currency in (("12,900원", "12900", "WON"), ("$19.99", 19.99, "USD")):
            with self.subTest(price=price):
                self.get_or_create.reset_mock()
                self.save.reset_mock()
                deal = self.process(
                    ArcaPipeline(),
                    overrides={
                        "origin_url": "/b/hotdeal/123",
                        "thumbnail": "//example.com/thumbnail.jpg",
                        "write_at": "2025-01-02 03:04:00",
                        "price": price,
                    },
                    prefix="arca",
                    defaults={
                        **self.common_defaults(),
                        "write_at": WRITE_AT.replace(tzinfo=ZoneInfo("UTC")),
                        "delivery_price": 0,
                        "community_name": "ARCA",
                        "price": expected_price,
                        "currency": currency,
                    },
                    updates={**self.common_updates(), "origin_url": "https://arca.live/b/hotdeal/123"},
                )
                self.assertEqual(deal.delivery_price, 3000)

    def test_eomisae_keeps_price_and_delivery_defaults(self):
        deal = self.process(
            EomisaePipeline(),
            overrides={"write_at": "2025-01-02 03:04:00"},
            prefix="eomisae",
            defaults={
                **self.common_defaults(),
                "write_at": WRITE_AT,
                "delivery_price": 0,
                "community_name": "EOMISAE",
                "price": 0,
                "currency": "WON",
            },
            updates={**self.common_updates(), "origin_url": COMMON_ITEM["origin_url"]},
        )
        self.assertEqual(deal.delivery_price, 3000)

    def test_coolnjoy_extracts_shop_and_leaves_dislike_count_unchanged(self):
        for price, expected_price, currency in (("12,900원", 12900.0, "WON"), ("$19.99", 19.99, "USD")):
            with self.subTest(price=price):
                self.get_or_create.reset_mock()
                self.save.reset_mock()
                deal = self.process(
                    CoolNJoyPipeline(),
                    overrides={"shop_name": "무시되는 값", "write_at": WRITE_AT, "price": price},
                    prefix="coolnjoy",
                    defaults={
                        **self.common_defaults(),
                        "origin_url": COMMON_ITEM["origin_url"],
                        "write_at": WRITE_AT,
                        "price": expected_price,
                        "currency": currency,
                        "community_name": "coolnjoy",
                    },
                    updates={"recommend_count": "7", "view_count": "150"},
                )
                self.assertEqual(deal.dislike_count, 99)

    def test_missing_counters_keep_site_specific_defaults(self):
        cases = (
            (PpomppuPipeline(), {"write_at": "2025-01-02 03:04"}, 0, 0),
            (FmKoreaPipeline(), {"create_at": "2025.01.02 03:04", "delivery_price": "무료"}, 0, 0),
            (ArcaPipeline(), {"write_at": "2025-01-02 03:04:00", "price": "100원", "delivery_price": "무료"}, 0, 0),
            (EomisaePipeline(), {"write_at": "2025-01-02 03:04:00"}, 0, 0),
            (CoolNJoyPipeline(), {"subject": "[쇼핑몰] 상품", "price": "100원"}, "", 99),
        )
        for pipeline, fields, recommend_count, dislike_count in cases:
            with self.subTest(pipeline=type(pipeline).__name__):
                deal = Deal(dislike_count=99)
                self.get_or_create.return_value = (deal, False)
                self.update_or_create.return_value = (deal, False)
                pipeline.process_item({"article_id": "123", **fields}, spider=None)
                self.assertEqual(deal.recommend_count, recommend_count)
                self.assertEqual(deal.dislike_count, dislike_count)
                self.assertEqual(deal.view_count, 0)

    def test_subject_price_patterns_keep_last_match_and_won_fallback(self):
        cases = (
            ("[쇼핑몰] 상품 (12,900원/무료)", "12900"),
            ("상품 (10,000원/무료) 쿠폰 (9,000원/무료)", "9000"),
            ("상품 3,500원 특가", "3500"),
            ("상품 8,000원 대신 7,000원 특가", "7000"),
            ("가격 정보 없음", 0),
        )
        for pipeline in (PpomppuPipeline(), FmKoreaPipeline()):
            for subject, expected in cases:
                with self.subTest(pipeline=type(pipeline).__name__, subject=subject):
                    self.get_or_create.return_value = (Deal(), False)
                    self.update_or_create.return_value = (Deal(), False)
                    pipeline.process_item({
                        **COMMON_ITEM,
                        "subject": subject,
                        "write_at": "2025-01-02 03:04",
                        "create_at": "2025.01.02 03:04",
                    }, spider=None)
                    method = self.update_or_create if isinstance(pipeline, FmKoreaPipeline) else self.get_or_create
                    self.assertEqual(method.call_args.kwargs["defaults"]["price"], expected)

    def test_invalid_dates_fail_before_writing(self):
        for pipeline in (PpomppuPipeline(), FmKoreaPipeline(), ArcaPipeline(), EomisaePipeline()):
            with self.subTest(pipeline=type(pipeline).__name__):
                with self.assertRaises(ValueError):
                    pipeline.process_item({**COMMON_ITEM, "write_at": "invalid", "create_at": "invalid"}, spider=None)
        self.get_or_create.assert_not_called()
        self.update_or_create.assert_not_called()
        self.save.assert_not_called()

    def test_fmkorea_structured_price_wins_over_quantity_in_title(self):
        deal=Deal(numeric_evidence=None)
        self.update_or_create.return_value=(deal,False)
        FmKoreaPipeline().process_item({**COMMON_ITEM,'subject':'콜라 355ml 24캔','price':'12,900원',
            'delivery_price':'3,000원','create_at':'2025.01.02 03:04'},spider=None)
        saved=self.update_or_create.call_args.kwargs['defaults']
        self.assertEqual(saved['price'],12900)
        self.assertEqual(saved['currency'],'KRW')
        self.assertEqual(deal.delivery_price,3000)
        self.assertEqual(deal.numeric_evidence['price'],'12,900원')

    def test_foreign_price_evidence_retains_cents(self):
        deal=Deal(numeric_evidence=None)
        self.get_or_create.return_value=(deal,False)
        ArcaPipeline().process_item({**COMMON_ITEM,'write_at':'2025-01-02 03:04:00','price':'$19.99'},spider=None)
        self.assertEqual(deal.numeric_evidence['price'],'$19.99')
        self.assertEqual(deal.numeric_evidence['currency'],'USD')
