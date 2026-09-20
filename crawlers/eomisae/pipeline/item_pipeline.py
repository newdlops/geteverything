from datetime import datetime

from crawlers.pipelines import DealPipeline


EOMISAE_PREFIX = "eomisae"


class EomisaePipeline(DealPipeline):
    article_id_prefix = EOMISAE_PREFIX
    community_label = "어미새"

    def get_defaults(self, item):
        write_at = datetime.strptime(item.get("write_at"), "%Y-%m-%d %H:%M:%S")
        return {
            **super().get_defaults(item),
            "write_at": write_at,
            "delivery_price": 0,
            "community_name": "EOMISAE",
            "price": 0,
            "currency": "WON",
        }

    def get_updates(self, item):
        return {
            **super().get_updates(item),
            "origin_url": item.get("origin_url", ""),
        }
