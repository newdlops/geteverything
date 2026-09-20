from django.test import SimpleTestCase
from scrapy import Request
from scrapy.exceptions import DropItem
from scrapy.http import HtmlResponse

from crawlers.coolnjoy.item_pipeline import CoolNJoyPipeline
from crawlers.coolnjoy.spider import CoolNJoySpider
from crawlers.eomisae.spider.spider import EomisaeSpider


class RecoveryParsingTests(SimpleTestCase):
    def test_eomisae_accepts_query_and_pretty_links_and_skips_ads(self):
        links = [
            '/index.php?document_srl=123&mid=fs', '/456',
            '/index.php?mid=fs&document_srl=789', '/advertisement', '',
        ]
        body = ''.join(
            f'<div class="card_el"><a class="pjax hx" href="{href}"></a>'
            '<h3><a class="pjax">A <b>deal</b></a></h3></div>'
            for href in links
        )
        request = Request('https://eomisae.co.kr/fs', meta={'cookiejar': 1})
        response = HtmlResponse(request.url, request=request, body=body, encoding='utf-8')
        results = list(EomisaeSpider().parse(response))
        self.assertEqual([r.cb_kwargs['data']['article_id'] for r in results], ['123', '456', '789'])
        self.assertTrue(all(r.cb_kwargs['data']['subject'] == 'A deal' for r in results))
        self.assertTrue(all(r.url.startswith('https://eomisae.co.kr/') for r in results))

    def test_coolnjoy_keeps_numeric_and_free_prices(self):
        for raw, expected in [('12,900원', (12900.0, 'WON')), ('$12.50', (12.5, 'USD')), (0, (0.0, 'WON'))]:
            with self.subTest(raw=raw):
                self.assertEqual(CoolNJoyPipeline.parse_price(raw), expected)

    def test_coolnjoy_drops_unknown_prices_before_database_writes(self):
        for price in ['본문참고', '종료됨', None, 'nan', '-1']:
            with self.subTest(price=price), self.assertRaises(DropItem):
                CoolNJoyPipeline.parse_price(price)

    def test_coolnjoy_skips_removed_detail(self):
        response = HtmlResponse('https://coolenjoy.net/bbs/jirum/123', body=b'<p>Removed</p>')
        self.assertEqual(list(CoolNJoySpider().detail_parse(response, {'article_id': '123'})), [])
