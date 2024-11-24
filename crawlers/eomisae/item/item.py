from scrapy.item import Item, Field


class EomisaeItem(Item):
    article_id = Field()
    origin_url = Field()
    shop_url_1 = Field()
    shop_name = Field()
    thumbnail = Field()
    subject = Field()
    content = Field() #
    category = Field()
    price = Field() #
    delivery_price = Field() #
    recommend_count = Field()
    dislike_count = Field()
    view_count = Field()
    create_at = Field()
    write_at = Field()
    update_at = Field() #
    crawled_at = Field() #
    is_end = Field() #
