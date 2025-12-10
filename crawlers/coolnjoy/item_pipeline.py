import re
from datetime import datetime

from gadmin.deals.models import Deal
from itemadapter import ItemAdapter

COOLNJOY_PREFIX = 'coolnjoy'

class CoolNJoyPipeline:
    def open_spider(self, spider):
        print('쿨엔조이 크롤링 시작')

    def close_spider(self, spider):
        print('쿨엔조이 크롤링 종료')

    def process_item(self, item, spider):
        c_item = ItemAdapter(item)

        print('쿨엔조이 처리중')

        price = c_item.get("price", 0)
        currency = 'WON'
        if '$' in price:
            price = float(price.replace('$', ''))
            currency = 'USD'
        else:
            if '원' in price:
                currency = 'WON'
            price = float(re.sub(r'[,원$]', '', price))

        if not isinstance(price, float):
            price = 0

        shop_name_pattern = r'^\[(.*?)\].*?$'
        shop_name = re.match(shop_name_pattern, c_item.get("subject", "")).group(1)

        cool_n_joy_item, _ = Deal.objects.get_or_create(article_id=COOLNJOY_PREFIX + c_item["article_id"],
                                                        defaults={
                                                            'origin_url': c_item.get("origin_url", ""),
                                                            'shop_url_1': c_item.get("shop_url_1", ""),
                                                            'shop_name': shop_name,
                                                            'thumbnail': c_item.get("thumbnail", ""),
                                                            'subject': c_item.get("subject", ""),
                                                            'category': c_item.get("category", ""),
                                                            'crawled_at': datetime.now(),
                                                            'write_at': c_item.get("write_at"),
                                                            'price': price,
                                                            'currency': currency,
                                                            'community_name': 'coolnjoy',
                                                        })

        cool_n_joy_item.recommend_count = c_item.get("recommend_count", "")
        cool_n_joy_item.view_count = c_item.get("view_count", 0)
        cool_n_joy_item.update_at = datetime.now()

        cool_n_joy_item.save()

        return item
