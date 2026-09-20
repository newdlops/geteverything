import os
import scrapy
import traceback
from urllib.parse import urlsplit
from w3lib.html import remove_tags

from scrapy import Request
from scrapy.exceptions import CloseSpider
from crawlers.utils.links import absolute_url, product_link
from crawlers.availability import AvailabilitySpiderMixin
if __name__ == 'spider.spider':
    from item import PpomppuItem # noqa
    from pipeline import PpomppuPipeline # noqa
else:
    from ..item import PpomppuItem
    from ..pipeline import PpomppuPipeline

class PpomppuSpider(AvailabilitySpiderMixin, scrapy.Spider):
    availability_site = 'ppomppu'
    name = "ppomppu_spider"
    request_headers = {
        "accept": "*/*",
        "accept-encoding": "gzip, deflate",
        "accept-language": "ko,en-US;q=0.9,en;q=0.8,ja;q=0.7,ko-KR;q=0.6,la;q=0.5,ru;q=0.4",
        "cache-control": "no-cache",
        "connection": "keep-alive",
        "pragma": "no-cache",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    }
    custom_settings = {
        'DOWNLOAD_DELAY': 2,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 1,
        'DOWNLOAD_TIMEOUT': 20,
        'RETRY_TIMES': 2,
        'DOWNLOADER_CLIENTCONTEXTFACTORY': 'scrapy.core.downloader.contextfactory.BrowserLikeContextFactory',
        'ITEM_PIPELINES': {
            PpomppuPipeline: 300,
        }
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.proxy_url = os.getenv('PPOMPPU_PROXY_URL', '').strip()
        if self.proxy_url:
            try:
                parsed = urlsplit(self.proxy_url)
                valid = (parsed.scheme == 'http' and parsed.hostname and parsed.port
                         and parsed.path in ('', '/') and not parsed.query and not parsed.fragment)
            except ValueError:
                valid = False
            if not valid:
                raise ValueError('PPOMPPU_PROXY_URL must be an HTTP proxy URL with a port') from None

    def request_meta(self, cookiejar):
        meta = {'cookiejar': cookiejar}
        if self.proxy_url:
            meta['proxy'] = self.proxy_url
        return meta

    # 수집할 웹사이트의 URL을 지정합니다.
    def start_requests(self):
        total_page = 5

        for i in range(1, total_page+1):
            yield scrapy.Request(
                f"https://www.ppomppu.co.kr/zboard/zboard.php?id=ppomppu&page={i}&divpage=96",
                callback=self.parse,
                headers=self.request_headers,
                meta=self.request_meta(i)
            )

        yield from self.availability_rechecks()

    def parse(self, response):
        rows = response.css('tr.bbs_new1')
        if not rows:
            raise CloseSpider('ppomppu_list_missing')
        for tr in rows:
            try:
                td = tr.css('td')
                if td is None:
                    continue
                article_id = td[0].xpath('string()').get()
                if article_id == '':
                    continue
                origin_url = td[1].css('a::attr(href)').get()
                thumbnail = absolute_url(td[1].css('a.baseList-thumb img::attr(src)').get(), response.url)
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
                    yield self.deal_request(url=detail_page_url, data=data, headers=self.request_headers,
                                            meta=self.request_meta(response.meta['cookiejar']))
            except Exception as e:
                print(f'목록 불러오는중에 에러 발생 : {e}')
                traceback.print_exc()
                raise Exception(f'목록 불러오는중 에러 발생')

    def detail_parse(self, response, data):
        try:
            shop_url_1 = product_link(response, 'li.topTitle-link a')

            recommend_count = response.css('span#vote_list_btn_txt::text').get()
            dislike_count = response.css('span#vote_anti_list_btn_txt::text').get()
            # content = response.css('td.board-contents').get()
            content = ''
            write_at = response.css('ul.topTitle-mainbox li::text')[0].get()[4:]
            yield PpomppuItem(dict(**data, shop_url_1=shop_url_1, recommend_count=recommend_count, dislike_count=dislike_count, content=content, write_at=write_at))
        except Exception as e:
            print(f'상세 페이지 불러오는중에 에러 발생 : {e}')
            traceback.print_exc()
            raise Exception(f'상세 페이지 불러오는중 에러 발생')
