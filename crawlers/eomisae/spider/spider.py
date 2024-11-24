import re

import scrapy
import os
import django

from w3lib.html import remove_tags, replace_escape_chars, strip_html5_whitespace

from scrapy import Request
if __name__ == 'spider.spider':
    from item import EomisaeItem # noqa
    from pipeline import EomisaePipeline # noqa
else:
    from ..item import EomisaeItem
    from ..pipeline import EomisaePipeline



os.environ['DJANGO_SETTINGS_MODULE'] = 'admin.settings'
django.setup()

class EomisaeSpider(scrapy.Spider):
    name = "eomisae_spider"
    custom_settings = {
        'DOWNLOAD_DELAY': 2,
        'ITEM_PIPELINES': {
            EomisaePipeline: 300,
        }
    }

    headers = {
        "accept": "*/*",
        "accept-encoding": "gzip, deflate, br, zstd",
        "accept-language": "ko,en-US;q=0.9,en;q=0.8,ja;q=0.7,ko-KR;q=0.6,la;q=0.5,ru;q=0.4",
        "cache-control": "no-cache",
        "connection": "keep-alive",
        "pragma": "no-cache",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    }

    # 수집할 웹사이트의 URL을 지정합니다.
    def start_requests(self):
        total_page = 5

        for i in range(1, total_page+1):
            yield scrapy.Request(
                f"https://eomisae.co.kr/index.php?mid=fs&page={i}",
                callback=self.parse,
                headers=self.headers,
                meta={'cookiejar': i}
            )

    def parse(self, response):
        for article in response.css('div.card_el'):
            try:
                origin_url = article.css('a.pjax.hx::attr(href)').get()

                id_pattern = r'document_srl\=(\d*?)$'
                article_id = re.search(id_pattern, origin_url).group(1)
                thumbnail = article.css('img.tmb::attr(src)').get()
                subject = strip_html5_whitespace(replace_escape_chars(article.css('h3 a.pjax::text').get()))




                # price = strip_html5_whitespace(replace_escape_chars(article.css('span.deal-price::text').get()))
                # delivery_price = strip_html5_whitespace(replace_escape_chars(article.css('span.deal-delivery::text').get()))

                data = {
                    'origin_url': origin_url, 'article_id': article_id,
                    'subject': subject,
                    'thumbnail': thumbnail,
                }

                if article_id != '':
                    yield Request(url=origin_url, callback=self.detail_parse, cb_kwargs=dict(data=data), headers=self.headers, meta={'cookiejar': response.meta['cookiejar']})
            except Exception as e:
                print(f'목록 불러오는중에 에러 발생 : {e}')

    def detail_parse(self, response, data):
        try:
            category = response.css('span[title=Category]::text').get()
            # shop_name = response.css('.col-title .deal-store::text').get()
            btm_area = response.css('div.btm_area span')
            recommend_count = btm_area[2].css('b::text').get()
            # dislike_count = btm_area[0].css('b::text').get()
            create_at = btm_area[5].css('::text').get()
            view_count = btm_area[1].css('b::text').get()
            shop_url_1 = response.css('td.extra_url a::attr(href)').get()


            yield EomisaeItem(dict(**data, shop_url_1=shop_url_1, recommend_count=recommend_count, create_at=create_at, view_count=view_count))
        except Exception as e:
            print(f'상세 페이지 불러오는중에 에러 발생 : {e}')
