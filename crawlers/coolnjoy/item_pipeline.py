import re
import math

from scrapy.exceptions import DropItem

from crawlers.pipelines import DealPipeline


COOLNJOY_PREFIX = "coolnjoy"


class CoolNJoyPipeline(DealPipeline):
    article_id_prefix = COOLNJOY_PREFIX
    community_label = "쿨엔조이"
    item_log_message = "쿨엔조이 처리중"

    def get_defaults(self, item):
        price, currency = self.parse_price(item.get("price", 0))
        shop_name = re.match(r"^\[(.*?)\].*?$", item.get("subject", "")).group(1)
        return {
            **super().get_defaults(item),
            "origin_url": item.get("origin_url", ""),
            "shop_name": shop_name,
            "write_at": item.get("write_at"),
            "price": price,
            "currency": currency,
            "community_name": "coolnjoy",
        }

    def get_updates(self, item):
        return {
            "recommend_count": item.get("recommend_count", ""),
            "view_count": item.get("view_count", 0),
        }

    @staticmethod
    def parse_price(price):
        price_text = "" if price is None else str(price)
        currency = "USD" if "$" in price_text else "WON"
        try:
            amount = float(re.sub(r"[,원$]", "", price_text))
        except ValueError:
            raise DropItem("Deal has no numeric price") from None
        if not math.isfinite(amount) or amount < 0:
            raise DropItem("Deal has no valid nonnegative price")
        return amount, currency
