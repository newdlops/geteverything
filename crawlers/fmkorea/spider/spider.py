import scrapy
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

class FmKoreaSpider(scrapy.Spider):
    name = "fm_korea_spider"
    custom_settings = {
        "LOG_LEVEL": "ERROR",
        'DOWNLOAD_DELAY': 10,
        'ITEM_PIPELINES': {
            FmKoreaPipeline: 300,
        },
        'CONCURRENT_REQUESTS': 1,
        'USER_AGENT': "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
        'DOWNLOADER_MIDDLEWARES' : {
            'rotating_proxies.middlewares.RotatingProxyMiddleware': 610,
            'rotating_proxies.middlewares.BanDetectionMiddleware': 620,
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
        total_page = 10

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

        for i in range(1, total_page + 1):
            yield scrapy.Request(
                f"https://www.fmkorea.com/?mid=hotdeal&sort_index=&order_type=desc&listStyle=webzine&cpage=4&page={i}",
                callback=self.parse,
                meta={'cookiejar': 1},
                headers=headers
            )

    def parse(self, response):
        # print(f'목록{response.body}')
        print(f'목록 처리')
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

                yield Request(url=f'https://www.fmkorea.com/?mid=hotdeal&sort_index=&order_type=desc&document_srl={article_id}&listStyle=webzine&cpage=1', callback=self.detail_parse, cb_kwargs=dict(data=data), meta={'cookiejar': response.meta['cookiejar']})
            except Exception as e:
                print(f'목록 불러오는중에 에러 발생 : {e}')

    def detail_parse(self, response, data):
        # print(f'디테일 {response.body}')
        print(f'디테일처리')
        try:
            table = response.css('table.hotdeal_table')
            community_name = '펨코'
            shop_url_1 = None
            shop_name = None
            price = None
            delivery_price = None
            view_count = None
            recommend_count = None
            comment_count = None
            create_at = None

            tr = table.css('tr')
            if len(tr) > 0:
                shop_url_1 = tr[0].css('div.xe_content a::text').get()
                shop_name = tr[1].css('div.xe_content::text').get()
                price = tr[3].css('div.xe_content::text').get()
                delivery_price = tr[4].css('div.xe_content::text').get()

            side_fr = response.css('div.side.fr')
            b = side_fr.css('b')
            if len(b) > 0:
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
            import traceback
            traceback.print_exc()
            print(f'상세 페이지 불러오는중에 에러 발생 : {e}')
