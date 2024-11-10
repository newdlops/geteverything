import scrapy
import os
import django
from w3lib.html import remove_tags, replace_escape_chars

from scrapy import Request
if __name__ == 'spider.spider':
    from item import FmKoreaItem # noqa
    from pipeline import FmKoreaPipeline # noqa
else:
    from ..item import FmKoreaItem
    from ..pipeline import FmKoreaPipeline



os.environ['DJANGO_SETTINGS_MODULE'] = 'admin.settings'
django.setup()

class FmKoreaSpider(scrapy.Spider):
    name = "fm_korea_spider"
    custom_settings = {
        'DOWNLOAD_DELAY': 1,
        'ITEM_PIPELINES': {
            FmKoreaPipeline: 300,
        },
        'CONCURRENT_REQUESTS': 1,
        'USER_AGENT': "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        'DOWNLOADER_MIDDLEWARES' : {
        'rotating_free_proxies.middlewares.RotatingProxyMiddleware': 610,
        'rotating_free_proxies.middlewares.BanDetectionMiddleware': 620,
        'scrapy.downloadermiddlewares.httpproxy.HttpProxyMiddleware': 110,
        },
        'NUMBER_OF_PROXIES_TO_FETCH': 10,
        'ROTATING_PROXY_LIST' : [
            '8.213.129.15:8080',
            '8.213.129.15:9090',
            '120.26.0.11:8880',
            '171.247.96.248:1080',
            '62.23.184.84:8080',
            '192.169.214.249:45108',
            '118.99.96.173:8080',
            '45.224.149.230:999',
            '115.147.20.37:8082',
            '103.176.97.166:8080',
            '180.180.175.11:8080',
            '8.213.222.157:4000',
            '95.43.244.15:4153',
            '39.175.75.52:30001',
            '120.26.52.35:8081',
            '103.168.44.191:8083',
            '150.136.4.250:3128',
            '43.255.113.232:85',
            '145.239.54.185:80',
            '39.102.213.213:80',
            '200.24.146.95:999',
            '47.238.134.126:80',
            '123.56.1.50:3129',
            '39.102.214.152:80',
            '177.53.154.218:999',
        ]
    }


    # 수집할 웹사이트의 URL을 지정합니다.
    def start_requests(self):
        total_page = 1

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
            shop_url_1 = tr[0].css('a::attr(src)').get()
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
