import scrapy
import os
import django
from w3lib.html import remove_tags, replace_escape_chars

from scrapy import Request
if __name__ == 'spider.spider':
    from item import FmKoreaItem # noqa
    from pipeline import FmKoreaPipeline # noqa
    from middlewares import SeleniumMiddleware # noqa
else:
    from ..item import FmKoreaItem
    from ..pipeline import FmKoreaPipeline
    from ..middlewares import SeleniumMiddleware


os.environ['DJANGO_SETTINGS_MODULE'] = 'admin.settings'
django.setup()

class FmKoreaSpider(scrapy.Spider):
    name = "fm_korea_spider"
    custom_settings = {
        'DOWNLOAD_DELAY': 2,
        'ITEM_PIPELINES': {
            FmKoreaPipeline: 300,
        },
        'CONCURRENT_REQUESTS': 1,
        'USER_AGENT': "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        'DOWNLOADER_MIDDLEWARES' : {
            SeleniumMiddleware: 100,
        },
    }


    # 수집할 웹사이트의 URL을 지정합니다.
    def start_requests(self):
        total_page = 10

        headers = {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "accept-encoding": "gzip, deflate, br, zstd",
            "accept-language": "ko,en-US;q=0.9,en;q=0.8,ja;q=0.7,ko-KR;q=0.6,la;q=0.5,ru;q=0.4",
            "cache-control": "no-cache",
            "connection": "keep-alive",
            "pragma": "no-cache",
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        }

        for i in range(1, total_page+1):
            yield scrapy.Request(
                f"https://www.fmkorea.com/index.php?mid=hotdeal&page={i}",
                callback=self.parse,
                meta={'cookiejar': 1},
                headers=headers
            )

    def parse(self, response):
        for li in response.css('div.fm_best_widget li'):
            try:
                article_id = li.css('h3.title a::attr(href)').get()[1:]
                origin_url = f'https://www.fmkorea.com/{article_id}'
                thumbnail = li.css('img.thumb::attr(src)').get()
                category = li.css('span.category a::text').get()
                subject = replace_escape_chars(remove_tags(li.css('h3.title a::text').get()))
                data = {
                    'origin_url': origin_url, 'article_id': article_id,
                    'subject': subject, 'category': category,
                    'thumbnail': thumbnail,
                }

                yield Request(url=origin_url, callback=self.detail_parse, cb_kwargs=dict(data=data), meta={'cookiejar': response.meta['cookiejar']})
            except Exception as e:
                print(f'목록 불러오는중에 에러 발생 : {e}')

    def detail_parse(self, response, data):
        try:
            table = response.css('table.hotdeal_table')
            tr = table.css('tr')
            shop_url_1 = tr[0].css('div.xe_content a::text').get()
            shop_name = tr[1].css('div.xe_content::text').get()
            community_name = '펨코'
            price = tr[3].css('div.xe_content::text').get()
            delivery_price = tr[4].css('div.xe_content::text').get()

            side_fr = response.css('div.side.fr')
            b = side_fr.css('b')

            view_count = b[0].css('::text').get()
            recommend_count = b[1].css('::text').get()
            comment_count = b[2].css('::text').get()

            create_at = response.css('span.date.m_no::text').get()

            yield FmKoreaItem(dict(**data,
                                   shop_name=shop_name,
                                   shop_url_1=shop_url_1,
                                   community_name=community_name,
                                   recommend_count=recommend_count,
                                   price=price,
                                   delivery_price=delivery_price,
                                   view_count=view_count,
                                   comment_count=comment_count,
                                   create_at=create_at))
        except Exception as e:
            print(f'상세 페이지 불러오는중에 에러 발생 : {e}')
