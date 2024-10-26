from scrapy.item import Item, Field


class PpomppuItem(Item):
    url = Field()
    subject = Field()
    category = Field()
    price = Field()
    recommend_count = Field()
    create_at = Field()
    crawled_at = Field()
    content = Field()
    a_link = Field()
    a_link2 = Field()
    b_link = Field()
    img = Field()
    cool_n_joy_id = Field()
