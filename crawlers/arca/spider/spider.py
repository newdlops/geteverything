import re

import scrapy
import os
import django
import traceback

from w3lib.html import remove_tags, replace_escape_chars, strip_html5_whitespace

from scrapy import Request
if __name__ == 'spider.spider':
    from item import ArcaItem # noqa
    from pipeline import ArcaPipeline # noqa
else:
    from ..item import ArcaItem
    from ..pipeline import ArcaPipeline



os.environ['DJANGO_SETTINGS_MODULE'] = 'admin.settings'
django.setup()

class ArcaSpider(scrapy.Spider):
    name = "arca_spider"
    custom_settings = {
        'DOWNLOAD_DELAY': 1,
        'ITEM_PIPELINES': {
            ArcaPipeline: 300,
        }
    }


    # 수집할 웹사이트의 URL을 지정합니다.
    def start_requests(self):
        total_page = 5

        headers = {
            "accept": "*/*",
            "accept-encoding": "gzip, deflate, br, zstd",
            "accept-language": "ko,en-US;q=0.9,en;q=0.8,ja;q=0.7,ko-KR;q=0.6,la;q=0.5,ru;q=0.4",
            "cache-control": "no-cache",
            "connection": "keep-alive",
            "pragma": "no-cache",
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        }

        for i in range(1, total_page+1):
            yield scrapy.Request(
                f"https://arca.live/b/hotdeal?p={i}",
                callback=self.parse,
                # headers=headers,
                meta={'cookiejar': i}
            )

    def parse(self, response):
        for article in response.css('div.list-table.hybrid .vrow.hybrid'):
            try:
                origin_url = article.css('a.title.hybrid-title::attr(href)').get()

                id_pattern = r'\/b\/hotdeal\/(.*?)\?p=\d'
                article_id = re.match(id_pattern, origin_url).groups()[0]
                thumbnail = article.css('.vrow-preview img::attr(src)').get()
                subject = strip_html5_whitespace(replace_escape_chars(article.css('a.title.hybrid-title::text')[1].get()))

                category = article.css('.col-title a.badge::text').get()
                shop_name = article.css('.col-title .deal-store::text').get()

                price = strip_html5_whitespace(replace_escape_chars(article.css('span.deal-price::text').get()))
                delivery_price = strip_html5_whitespace(replace_escape_chars(article.css('span.deal-delivery::text').get()))

                data = {
                    'origin_url': origin_url, 'article_id': article_id,
                    'subject': subject, 'category': category,
                    'thumbnail': thumbnail, 'shop_name': shop_name, 'price': price, 'delivery_price': delivery_price,
                }

                detail_page_url = f"https://arca.live{origin_url}"
                if article_id != '':
                    yield Request(url=detail_page_url, callback=self.detail_parse, cb_kwargs=dict(data=data), meta={'cookiejar': response.meta['cookiejar']})
            except Exception as e:
                print(f'목록 불러오는중에 에러 발생 : {e}')
                traceback.print_exc()
                raise Exception(f'목록 불러오는중 에러 발생')

    def detail_parse(self, response, data):
        try:
            article_info = response.css('div.article-info')
            info_spans = article_info.css('span')
            recommend_count = info_spans[1].css('::text').get()
            dislike_count = info_spans[4].css('::text').get()
            write_at = info_spans[11].css('time::text').get()
            view_count = info_spans[10].css('::text').get()
            shop_url_1 = response.css('tbody tr a::text').get()


            yield ArcaItem(dict(**data, shop_url_1=shop_url_1, recommend_count=recommend_count, dislike_count=dislike_count, view_count=view_count, write_at=write_at))
        except Exception as e:
            print(f'상세 페이지 불러오는중에 에러 발생 : {e}')
            traceback.print_exc()
            raise Exception(f'상세 페이지 불러오는중 에러 발생')
