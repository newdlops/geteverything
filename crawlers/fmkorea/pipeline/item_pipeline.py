from datetime import datetime
from decimal import Decimal

from crawlers.pipelines import DealPipeline
from crawlers.utils.prices import extract_subject_price
from gadmin.metrics.money import price_text


FMKOREA_PREFIX = "fm"
COMMUNITY_NAME = "FMKOREA"


class FmKoreaPipeline(DealPipeline):
    article_id_prefix = FMKOREA_PREFIX
    community_label = COMMUNITY_NAME
    update_existing_defaults = True

    def open_spider(self, spider):
        super().open_spider(spider)
        print("현재 KST:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def get_defaults(self, item):
        create_at = datetime.strptime(item.get("create_at"), "%Y.%m.%d %H:%M")
        collected = price_text(item.get("price"), 'KRW', bare=True)
        price = int(Decimal(collected['amount'])) if collected else extract_subject_price(item.get("subject", ""))
        return {
            **super().get_defaults(item),
            "origin_url": item.get("origin_url", ""),
            "create_at": create_at,
            "write_at": create_at,
            "price": price,
            **({'currency':collected['currency']} if collected and collected['currency'] else {}),
        }

    def get_updates(self, item):
        return {
            **super().get_updates(item),
            "delivery_price": self.extract_number(item.get("delivery_price", 0)),
            "community_name": COMMUNITY_NAME,
        }

    def extract_number(self, text):
        """Parse the entire delivery amount, including thousands separators."""
        parsed = price_text(text, 'KRW', bare=True)
        return int(Decimal(parsed['amount'])) if parsed else 0
