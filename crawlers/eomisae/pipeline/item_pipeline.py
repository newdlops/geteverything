import re
from datetime import datetime
from zoneinfo import ZoneInfo
from gadmin.deals.models import Deal
from itemadapter import ItemAdapter

EOMISAE_PREFIX = 'eomisae'

class EomisaePipeline:
    def open_spider(self, spider):
        print('어미새 크롤링 시작')

    def close_spider(self, spider):
        print('어미새 크롤링 종료')

    def process_item(self, item, spider):
        print('어미새 핫딜 처리중')
        c_item = ItemAdapter(item)

        date_format = '%Y-%m-%d %H:%M:%S'
        write_at = datetime.strptime(c_item.get("write_at"), date_format)

        crawl_item, _ = Deal.objects.get_or_create(article_id=EOMISAE_PREFIX + c_item["article_id"],
                                                          defaults={
                                                              'shop_url_1': c_item.get("shop_url_1", ""),
                                                              'shop_name': c_item.get("shop_name", ""),
                                                              'thumbnail': c_item.get("thumbnail", ""),
                                                              'subject': c_item.get("subject", ""),
                                                              'category': c_item.get("category", ""),
                                                              'crawled_at': datetime.now(),
                                                              'write_at': write_at,
                                                              'delivery_price': 0,
                                                              'community_name': 'EOMISAE',
                                                              'price': 0,
                                                              'currency': 'WON'
                                                          })

        crawl_item.origin_url = c_item.get("origin_url", "")
        crawl_item.recommend_count = c_item.get("recommend_count", 0)
        crawl_item.dislike_count = c_item.get("dislike_count", 0)
        crawl_item.view_count = c_item.get("view_count", 0)

        crawl_item.update_at = datetime.now()


        crawl_item.save()

        return item
