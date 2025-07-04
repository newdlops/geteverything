import re
from datetime import datetime
from deals.models import Deal
from itemadapter import ItemAdapter

FMKOREA_PREFIX = 'fm'
COMMUNITY_NAME = 'FMKOREA'

class FmKoreaPipeline:
    def open_spider(self, spider):
        print(f'{COMMUNITY_NAME} 크롤링 시작')
        print("현재 KST:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def close_spider(self, spider):
        print(f'{COMMUNITY_NAME} 크롤링 종료')

    def process_item(self, item, spider):
        print(f'{COMMUNITY_NAME} 핫딜 처리중')
        c_item = ItemAdapter(item)

        date_format = '%Y.%m.%d %H:%M'
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


        crawl_item, _ = Deal.objects.update_or_create(article_id=FMKOREA_PREFIX + c_item["article_id"],
                                                          defaults={
                                                              'origin_url': c_item.get("origin_url", ""),
                                                              'shop_url_1': c_item.get("shop_url_1", ""),
                                                              'shop_name': c_item.get("shop_name", ""),
                                                              'thumbnail': c_item.get("thumbnail", ""),
                                                              'subject': c_item.get("subject", ""),
                                                              # 'content': c_item.get("content", ""),
                                                              'category': c_item.get("category", ""),
                                                              'crawled_at': datetime.now(),
                                                              'create_at': create_at,
                                                              'write_at': create_at,
                                                              'price': price,
                                                          })

        crawl_item.delivery_price = self.extract_number(c_item.get("delivery_price", 0))
        crawl_item.recommend_count = c_item.get("recommend_count", 0)
        crawl_item.dislike_count = c_item.get("dislike_count", 0)
        crawl_item.view_count = c_item.get("view_count", 0)
        crawl_item.community_name = COMMUNITY_NAME
        crawl_item.update_at = datetime.now()


        crawl_item.save()

        return item

    def extract_number(self, text):
        """
        문자열에서 숫자를 추출하여 반환하며, '무료'가 포함된 경우 0을 반환합니다.
        """
        if "무료" in text:
            return 0
        numbers = re.findall(r'\d+', text)
        return int(numbers[0]) if numbers else 0
