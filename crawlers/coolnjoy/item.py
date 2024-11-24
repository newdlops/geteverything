from scrapy.item import Item, Field


class CoolNJoyItem(Item):
    origin_url = Field()
    subject = Field()
    category = Field()
    price = Field()
    recommend_count = Field()
    create_at = Field()
    write_at = Field()
    crawled_at = Field()
    shop_url_1 = Field()
    thumbnail = Field()
    article_id = Field()
    shop_name = Field()
    view_count = Field()

