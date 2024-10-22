from datetime import timezone

from coolnjoy.models import CoolNJoyDeal
from itemadapter import ItemAdapter


class CoolNJoyPipeline:
    def open_spider(self, spider):
        print('열렸어요')

    def close_spider(self, spider):
        print('닫혔어요')

    def process_item(self, item, spider):
        c_item = ItemAdapter(item)

        print('처리중')

        cool_n_joy_item, _ = CoolNJoyDeal.objects.get_or_create(cool_n_joy_id=c_item["cool_n_joy_id"])

        cool_n_joy_item.url = c_item.get("url", "")
        cool_n_joy_item.subject = c_item.get("subject", "")
        cool_n_joy_item.category = c_item.get("category", "")
        cool_n_joy_item.price = c_item.get("price", "")
        cool_n_joy_item.recommend_count = c_item.get("recommend_count", "")
        if c_item.get("created_at"):
            cool_n_joy_item.create_at = c_item.get("create_at")
        if c_item.get("crawled_at"):
            cool_n_joy_item.crawled_at = c_item.get("crawled_at")
        cool_n_joy_item.content = c_item.get("content", "")
        cool_n_joy_item.a_link = c_item.get("a_link", "")
        cool_n_joy_item.a_link2 = c_item.get("a_link2", "")
        cool_n_joy_item.b_link = c_item.get("b_link", "")
        cool_n_joy_item.img = c_item.get("img", "")
        cool_n_joy_item.cool_n_joy_id = c_item.get("cool_n_joy_id", "")
        cool_n_joy_item.save()

        return item
