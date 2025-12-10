import re
from datetime import datetime, tzinfo
from zoneinfo import ZoneInfo  # Python 3.9 이상


from gadmin.deals.models import Deal
from itemadapter import ItemAdapter

ARCA_PREFIX = 'arca'

class ArcaPipeline:
    def open_spider(self, spider):
        print('아카라이브 크롤링 시작')

    def close_spider(self, spider):
        print('아카라이브 크롤링 종료')

    def process_item(self, item, spider):
        print('아카라이브 핫딜 처리중')
        c_item = ItemAdapter(item)

        date_format = '%Y-%m-%d %H:%M:%S'
        utc = ZoneInfo('UTC')
        write_at = datetime.strptime(c_item.get("write_at"), date_format).replace(tzinfo=utc)
        price = c_item.get("price", 0)
        currency = 'WON'
        if '$' in price:
            price = float(price.replace('$', ''))
            currency = 'USD'
        else:
            if '원' in price:
               currency = 'WON'
            price = re.sub(r'[,원$]', '', price)

        delivery_price = c_item.get("delivery_price", 0)
        delivery_price = 0 if delivery_price == '무료' else re.sub(r'[,원$]', '', delivery_price)

        crawl_item, _ = Deal.objects.get_or_create(article_id=ARCA_PREFIX + c_item["article_id"],
                                                          defaults={
                                                              'shop_url_1': c_item.get("shop_url_1", ""),
                                                              'shop_name': c_item.get("shop_name", ""),
                                                              'thumbnail': f'https:{c_item.get("thumbnail", "")}',
                                                              'subject': c_item.get("subject", ""),
                                                              'category': c_item.get("category", ""),
                                                              'crawled_at': datetime.now(),
                                                              'write_at': write_at,
                                                              'delivery_price': delivery_price,
                                                              'community_name': 'ARCA',
                                                              'price': price,
                                                              'currency': currency
                                                          })

        crawl_item.origin_url = f"https://arca.live{c_item.get("origin_url", "")}"
        crawl_item.recommend_count = c_item.get("recommend_count", 0)
        crawl_item.dislike_count = c_item.get("dislike_count", 0)
        crawl_item.view_count = c_item.get("view_count", 0)

        crawl_item.update_at = datetime.now()


        crawl_item.save()

        return item
