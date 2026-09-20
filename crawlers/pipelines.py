"""Shared persistence flow for site-specific deal pipelines."""

from datetime import datetime

from itemadapter import ItemAdapter
from scrapy.exceptions import DropItem

from gadmin.deals.models import Deal


class DealPipeline:
    article_id_prefix = ""
    community_label = ""
    item_log_message = ""
    update_existing_defaults = False

    def open_spider(self, spider):
        print(f"{self.community_label} 크롤링 시작")

    def close_spider(self, spider):
        print(f"{self.community_label} 크롤링 종료")

    def process_item(self, item, spider):
        print(self.item_log_message or f"{self.community_label} 핫딜 처리중")
        adapted_item = ItemAdapter(item)
        observation = adapted_item.get('_availability')
        if adapted_item.get('_status_only'):
            self.record_availability(adapted_item, observation, spider)
            raise DropItem('Availability observation stored; not a newly scraped deal')
        defaults = self.get_defaults(adapted_item)

        if self.update_existing_defaults:
            refreshed = {key: value for key, value in defaults.items() if key != "thumbnail"}
            deal, _ = Deal.objects.update_or_create(
                article_id=self.article_id_prefix + adapted_item["article_id"],
                defaults=refreshed,
                create_defaults=defaults,
            )
        else:
            deal, _ = Deal.objects.get_or_create(
                article_id=self.article_id_prefix + adapted_item["article_id"],
                defaults=defaults,
            )

        updates = self.get_updates(adapted_item)
        # Preserve the original decimals and shipping text before integer legacy fields
        # lose precision. Stable evidence does not cause repeated measurement jobs.
        evidence = dict(deal.numeric_evidence or {})
        incoming = {}
        for field, key in (("price", "price"), ("delivery_price", "delivery")):
            value = adapted_item.get(field)
            if value is not None and str(value).strip() not in ("", "0"):
                incoming[key] = str(value).strip()[:256]
        if incoming:
            evidence.update(incoming)
            if defaults.get("currency"):
                evidence["currency"] = defaults["currency"]
            if evidence != deal.numeric_evidence:
                updates["numeric_evidence"] = evidence
        shop_url = adapted_item.get("shop_url_1")
        if isinstance(shop_url, str) and shop_url.startswith(("http://", "https://")):
            updates["shop_url_1"] = shop_url
        for field, value in updates.items():
            setattr(deal, field, value)
        deal.update_at = datetime.now()
        # The image worker can publish concurrently; never write a stale thumbnail back.
        deal.save(update_fields=[*updates, "update_at"])
        if observation:
            self.record_availability(adapted_item, observation, spider)
        return item

    def record_availability(self, item, observation, spider):
        from crawlers.availability_store import record_observation
        status = record_observation(self.article_id_prefix + item['article_id'], observation)
        if spider is not None and status is not None:
            spider.crawler.stats.inc_value('availability/' + observation['outcome'])

    def get_defaults(self, item: ItemAdapter) -> dict:
        """Fields used on creation, or also on recrawl when explicitly enabled."""
        return {
            "shop_url_1": item.get("shop_url_1", ""),
            "shop_name": item.get("shop_name", ""),
            "thumbnail": item.get("thumbnail", ""),
            "subject": item.get("subject", ""),
            "category": item.get("category", ""),
            "crawled_at": datetime.now(),
        }

    def get_updates(self, item: ItemAdapter) -> dict:
        """Fields refreshed on every crawl, including existing deals."""
        return {
            "recommend_count": item.get("recommend_count", 0),
            "dislike_count": item.get("dislike_count", 0),
            "view_count": item.get("view_count", 0),
        }
