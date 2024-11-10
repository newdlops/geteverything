import re
from datetime import timezone

from deals.models import Deal
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
            price = re.sub(r'[,원$]', '', price)


        cool_n_joy_item, _ = Deal.objects.get_or_create(article_id=COOLNJOY_PREFIX + c_item["article_id"])

        cool_n_joy_item.origin_url = c_item.get("origin_url", "")
        cool_n_joy_item.subject = c_item.get("subject", "")
        cool_n_joy_item.category = c_item.get("category", "")
        cool_n_joy_item.price = price
        cool_n_joy_item.recommend_count = c_item.get("recommend_count", "")
        if c_item.get("created_at"):
            cool_n_joy_item.create_at = c_item.get("create_at")
        if c_item.get("crawled_at"):
            cool_n_joy_item.crawled_at = c_item.get("crawled_at")
        cool_n_joy_item.content = c_item.get("content", "")
        cool_n_joy_item.shop_url_1 = c_item.get("shop_url_1", "")
        cool_n_joy_item.thumbnail = c_item.get("thumbnail", "")
        cool_n_joy_item.currency = currency
        cool_n_joy_item.community_name = 'coolnjoy'

        cool_n_joy_item.save()

        return item
