import re
from datetime import datetime
from ppomppu.models import PpomppuDeal
from itemadapter import ItemAdapter


class PpomppuPipeline:
    def open_spider(self, spider):
        print('뽐뿌 크롤링 시작')

    def close_spider(self, spider):
        print('뽐뿌 크롤링 종료')

    def process_item(self, item, spider):
        print('뽐뿌 핫딜 처리중')
        c_item = ItemAdapter(item)

        date_format = '%Y-%m-%d %H:%M'
        create_at = datetime.strptime(c_item.get("create_at"), date_format)

        remove_pattern = r'[ㄱ-ㅎ가-힣|\\(\),/ ~]'
        pattern = r'(?<!\d)(?:\d{1,3}(?:,\d{3})+|\d+)(?:[ㄱ-ㅎ가-힣])*(?=[^1234567890ㄱ-ㅎ가-힣]*/\s*|$)'
        pattern2 = r'(?<!\d)(?:\d{1,3}(?:,\d{3})*|\d+)(?:원)+'
        price = re.findall(pattern, c_item.get("subject", ""))
        if len(price) == 1:
            price = re.sub(remove_pattern,'',price[0])
        elif len(price) > 1:
            price = re.sub(remove_pattern,'',price[len(price)-1])
        else:
            price = re.findall(pattern2,c_item.get("subject", ""))
            if len(price) == 1:
                price = re.sub(remove_pattern,'',price[0])
            elif len(price) > 1:
                price = re.sub(remove_pattern,'',price[len(price)-1])
            else:
                price = 0


        crawl_item, _ = PpomppuDeal.objects.get_or_create(article_id=c_item["article_id"],
                                                          defaults={
                                                              'origin_url': c_item.get("origin_url", ""),
                                                              'shop_url_1': c_item.get("shop_url_1", ""),
                                                              'shop_name': c_item.get("shop_name", ""),
                                                              'thumbnail': c_item.get("thumbnail", ""),
                                                              'subject': c_item.get("subject", ""),
                                                              'content': c_item.get("content", ""),
                                                              'category': c_item.get("category", ""),
                                                              'crawled_at': datetime.now(),
                                                              'create_at': create_at,
                                                              'price': price,
                                                          })

        crawl_item.delivery_price = c_item.get("delivery_price", 0)
        crawl_item.recommend_count = c_item.get("recommend_count", 0)
        crawl_item.dislike_count = c_item.get("dislike_count", 0)
        crawl_item.view_count = c_item.get("view_count", 0)

        crawl_item.update_at = datetime.now()


        crawl_item.save()

        return item
