from datetime import datetime

from crawlers.pipelines import DealPipeline
from crawlers.utils.prices import extract_subject_price


# Keep the stored prefix for compatibility with previously collected deals.
PPOMPPU_PREFIX = "ppompu"


class PpomppuPipeline(DealPipeline):
    article_id_prefix = PPOMPPU_PREFIX
    community_label = "뽐뿌"

    def get_defaults(self, item):
        write_at = datetime.strptime(item.get("write_at"), "%Y-%m-%d %H:%M")
        price = extract_subject_price(item.get("subject", ""))
        return {
            **super().get_defaults(item),
            "origin_url": f'https://www.ppomppu.co.kr/zboard/{item.get("origin_url", "")}',
            "write_at": write_at,
            "price": price,
            "community_name": "PPOMPPU",
        }

    def get_updates(self, item):
        return {
            **super().get_updates(item),
            "delivery_price": item.get("delivery_price", 0),
        }
