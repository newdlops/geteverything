import re

import scrapy
import os
import django

from w3lib.html import remove_tags

from scrapy import Request
if __name__ == 'spider.spider':
    from item import PpomppuItem # noqa
    from pipeline import PpomppuPipeline # noqa
else:
    from ..item import PpomppuItem
    from ..pipeline import PpomppuPipeline



os.environ['DJANGO_SETTINGS_MODULE'] = 'admin.settings'
django.setup()

class PpomppuSpider(scrapy.Spider):
    name = "ppomppu_spider"
    custom_settings = {
        'DOWNLOAD_DELAY': 1,
        'ITEM_PIPELINES': {
            PpomppuPipeline: 300,
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
                f"https://www.ppomppu.co.kr/zboard/zboard.php?id=ppomppu&page={i}&divpage=96",
                callback=self.parse,
                headers=headers,
                meta={'cookiejar': i}
            )

    def parse(self, response):
        for tr in response.css('tr.bbs_new1'):
            try:
                td = tr.css('td')
                if td is None:
                    continue
                article_id = td[0].xpath('string()').get()
                if article_id == '':
                    continue
                origin_url = td[1].css('a::attr(href)').get()
                thumbnail = td[1].css('a.baseList-thumb img::attr(src)').get()
                category = td[1].css('small::text').get()[1:-1]
                shop_name = td[1].css('a.baseList-title span em::text').get()[1:-1]
                subject = remove_tags(td[1].css('a.baseList-title span::text').get())
                view_count = td[5].xpath('string()').get()
                data = {
                    'origin_url': origin_url, 'article_id': article_id,
                    'subject': subject, 'category': category,
                    'thumbnail': thumbnail, 'shop_name': shop_name, 'view_count': view_count
                }

                detail_page_url = f"https://www.ppomppu.co.kr/zboard/{origin_url}"
                if td is not None and article_id != '':
                    yield Request(url=detail_page_url, callback=self.detail_parse, cb_kwargs=dict(data=data), meta={'cookiejar': response.meta['cookiejar']})
            except Exception as e:
                print(f'목록 불러오는중에 에러 발생 : {e}')

    def detail_parse(self, response, data):
        try:
            shop_url_1 = response.css('li.topTitle-link a::text').get()

            recommend_count = response.css('span#vote_list_btn_txt::text').get()
            dislike_count = response.css('span#vote_anti_list_btn_txt::text').get()
            content = response.css('td.board-contents').get()
            create_at = response.css('ul.topTitle-mainbox li::text')[0].get()[4:]
            yield PpomppuItem(dict(**data, shop_url_1=shop_url_1, recommend_count=recommend_count, dislike_count=dislike_count, content=content, create_at=create_at))
        except Exception as e:
            print(f'상세 페이지 불러오는중에 에러 발생 : {e}')
