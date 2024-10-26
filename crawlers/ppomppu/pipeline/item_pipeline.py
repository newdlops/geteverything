# from ppomppu.models import PpomppuDeal
# from itemadapter import ItemAdapter


class PpomppuPipeline:
    def open_spider(self, spider):
        print('뽐뿌 크롤링 시작')

    def close_spider(self, spider):
        print('뽐뿌 크롤링 종료')

    def process_item(self, item, spider):
        # c_item = ItemAdapter(item)

        print('뽐뿌 핫딜 처리중')

        # crawl_item, _ = PpomppuDeal.objects.get_or_create(cool_n_joy_id=c_item["cool_n_joy_id"])
        #
        # crawl_item.url = c_item.get("url", "")
        # crawl_item.subject = c_item.get("subject", "")
        # crawl_item.category = c_item.get("category", "")
        # crawl_item.price = c_item.get("price", "")
        # crawl_item.recommend_count = c_item.get("recommend_count", "")
        # if c_item.get("created_at"):
        #     crawl_item.create_at = c_item.get("create_at")
        # if c_item.get("crawled_at"):
        #     crawl_item.crawled_at = c_item.get("crawled_at")
        # crawl_item.content = c_item.get("content", "")
        # crawl_item.a_link = c_item.get("a_link", "")
        # crawl_item.a_link2 = c_item.get("a_link2", "")
        # crawl_item.b_link = c_item.get("b_link", "")
        # crawl_item.img = c_item.get("img", "")
        # crawl_item.cool_n_joy_id = c_item.get("cool_n_joy_id", "")
        # crawl_item.save()

        return item
