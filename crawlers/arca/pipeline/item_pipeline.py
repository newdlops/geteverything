import re
from datetime import datetime
from zoneinfo import ZoneInfo

from crawlers.pipelines import DealPipeline
from crawlers.utils.links import absolute_url


ARCA_PREFIX = "arca"


class ArcaPipeline(DealPipeline):
    article_id_prefix = ARCA_PREFIX
    community_label = "아카라이브"

    def get_defaults(self, item):
        write_at = datetime.strptime(item.get("write_at"), "%Y-%m-%d %H:%M:%S")
        write_at = write_at.replace(tzinfo=ZoneInfo("UTC"))
        price, currency = self.parse_price(item.get("price", 0))
        delivery_price = item.get("delivery_price", 0)
        delivery_price = 0 if delivery_price == "무료" else re.sub(r"[,원$]", "", delivery_price)
        return {
            **super().get_defaults(item),
            "thumbnail": absolute_url(item.get("thumbnail"), 'https://arca.live/'),
            "write_at": write_at,
            "delivery_price": delivery_price,
            "community_name": "ARCA",
            "price": price,
            "currency": currency,
        }

    def get_updates(self, item):
        return {
            **super().get_updates(item),
            "origin_url": f'https://arca.live{item.get("origin_url", "")}',
        }

    @staticmethod
    def parse_price(price):
        if "$" in price:
            return float(price.replace("$", "")), "USD"
        return re.sub(r"[,원$]", "", price), "WON"
