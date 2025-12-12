import re
import traceback
from datetime import datetime

import scrapy
from w3lib.html import remove_tags, replace_escape_chars, strip_html5_whitespace

from scrapy import Request
from crawlers.arca.item import ArcaItem
from crawlers.arca.pipeline import ArcaPipeline
from crawlers.middlewares import SeleniumMiddleware


class ArcaSpider(scrapy.Spider):
    name = "arca_spider"
    custom_settings = {
        'DOWNLOAD_DELAY': 10,
        'ITEM_PIPELINES': {
            ArcaPipeline: 300,
        },
        'CONCURRENT_REQUESTS': 1,
        # 'USER_AGENT': "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
        'DOWNLOADER_MIDDLEWARES' : {
            # 'rotating_proxies.middlewares.RotatingProxyMiddleware': 610,
            # 'rotating_proxies.middlewares.BanDetectionMiddleware': 620,
            SeleniumMiddleware: 700,
        },
        'ROTATING_PROXY_LIST': [
            '123.141.181.8:5031',    # 수집: free‑proxy‑list.net :contentReference[oaicite:1]{index=1}
            '123.141.181.1:5031',    # 수집: free‑proxy‑list.net :contentReference[oaicite:2]{index=2}
            '59.7.246.4:80',         # 수집: free‑proxy‑list.net :contentReference[oaicite:3]{index=3}
            '118.47.179.203:80',     # 수집: free‑proxy‑list.net :contentReference[oaicite:4]{index=4}
            '123.140.146.20:5031',   # 수집: free‑proxy‑list.net :contentReference[oaicite:5]{index=5}
            '146.56.162.25:80',      # 수집: ProxyScrape :contentReference[oaicite:6]{index=6}
            '8.213.128.90:50001',    # 수집: ProxyScrape :contentReference[oaicite:7]{index=7}
            '123.141.181.7:5031',    # 수집: proxy‑list.download :contentReference[oaicite:8]{index=8}
            '13.125.7.17:3128',      # 수집: FineProxy :contentReference[oaicite:9]{index=9}
            '123.140.160.99:5031',   # 수집: FineProxy :contentReference[oaicite:10]{index=10}
        ],
    }


    # 수집할 웹사이트의 URL을 지정합니다.
    def start_requests(self):
        total_page = 5

        headers = {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "accept-encoding": "gzip, deflate, br, zstd",
            "accept-language": "ko,en-US;q=0.9,en;q=0.8,ja;q=0.7,ko-KR;q=0.6,la;q=0.5,ru;q=0.4",
            "cache-control": "no-cache",
            "pragma": "no-cache",
            "priority": "u=0, i",
            "sec-ch-ua": "\"Google Chrome\";v=\"137\", \"Chromium\";v=\"137\", \"Not/A)Brand\";v=\"24\"",
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": "\"macOS\"",
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "none",
            "sec-fetch-user": "?1",
            "upgrade-insecure-requests": "1",
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
        }

        for i in range(1, total_page+1):
            yield scrapy.Request(
                f"https://arca.live/b/hotdeal?p={i}",
                callback=self.parse,
                # headers=headers,
                meta={'cookiejar': i}
            )

    def parse(self, response):
        try:
            print(f'arca 목록 처리 {response.body}')
            list = response.css('div.list-table.hybrid .vrow.hybrid')
            print(f'arca {len(list)}개 발견')
            for article in list:
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
            traceback.print_exc()
            print(f'[Error :{datetime.now()}]아카라이브 목록 불러오는중에 에러 발생 : {e}')

    def detail_parse(self, response, data, datatime=None):
        try:
            print(f'arca 디테일 처리')
            article_info = response.css('div.article-info')
            info_spans = article_info.css('span')
            recommend_count = info_spans[1].css('::text').get()
            dislike_count = info_spans[4].css('::text').get()
            write_at = info_spans[11].css('time::text').get()
            view_count = info_spans[10].css('::text').get()
            shop_url_1 = response.css('tbody tr a::text').get()


            yield ArcaItem(dict(**data, shop_url_1=shop_url_1, recommend_count=recommend_count, dislike_count=dislike_count, view_count=view_count, write_at=write_at))
        except Exception as e:
            traceback.print_exc()
            print(f'[Error :{datetime.now()}]아카라이브 상세 페이지 불러오는중에 에러 발생 : {e}')
