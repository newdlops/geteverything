import os
from unittest.mock import patch

from django.test import SimpleTestCase
from scrapy.exceptions import CloseSpider
from scrapy.http import HtmlResponse

from crawlers.ppomppu.spider.spider import PpomppuSpider
from crawlers.ppomppu.crawler.crawler import crawl


LIST_HTML = b'''<table><tr class="bbs_new1"><td>123</td><td>
<a class="baseList-thumb" href="view.php?id=ppomppu&amp;no=123"><img src="/thumb.jpg"></a>
<small>[etc]</small><a class="baseList-title"><span><em>[shop]</em>Product (12,900)</span></a>
</td><td></td><td></td><td></td><td>42</td></tr></table>'''


class PpomppuProxyTests(SimpleTestCase):
    def setUp(self):
        self.enterContext(patch('crawlers.availability_store.due_deals', return_value=[]))

    def requests_for(self, proxy):
        with patch.dict(os.environ, {'PPOMPPU_PROXY_URL': proxy}):
            spider = PpomppuSpider()
        lists = list(spider.start_requests())
        response = HtmlResponse(lists[0].url, request=lists[0], body=LIST_HTML, encoding='utf-8')
        return lists, list(spider.parse(response))

    def test_proxy_covers_both_lists_and_details_without_changing_source_urls(self):
        lists, details = self.requests_for(' http://127.0.0.1:18888 ')
        self.assertEqual(len(lists), 5)
        self.assertEqual(len(details), 1)
        for request in lists + details:
            self.assertEqual(request.meta['proxy'], 'http://127.0.0.1:18888')
            self.assertTrue(request.url.startswith('https://www.ppomppu.co.kr/zboard/'))
        self.assertEqual(details[0].meta['cookiejar'], lists[0].meta['cookiejar'])
        self.assertEqual(details[0].headers, lists[0].headers)
        self.assertIn(b'Mozilla/', details[0].headers[b'User-Agent'])
        self.assertEqual(details[0].headers[b'Accept-Encoding'], b'gzip, deflate')
        self.assertEqual(details[0].cb_kwargs['data']['article_id'], '123')

    def test_unset_proxy_preserves_direct_requests(self):
        lists, details = self.requests_for('')
        self.assertTrue(all('proxy' not in request.meta for request in lists + details))

    def test_invalid_proxy_does_not_echo_credentials(self):
        with patch.dict(os.environ, {'PPOMPPU_PROXY_URL': 'socks5://user:private-password@localhost:1080'}):
            with self.assertRaises(ValueError) as error:
                PpomppuSpider()
        self.assertNotIn('private-password', str(error.exception))

    def test_error_html_with_http_200_is_not_an_empty_success(self):
        response = HtmlResponse('https://www.ppomppu.co.kr/zboard/zboard.php?id=ppomppu',
                                body=b'<html><title>403 Forbidden</title></html>')
        with self.assertRaises(CloseSpider) as error:
            list(PpomppuSpider().parse(response))
        self.assertEqual(error.exception.reason, 'ppomppu_list_missing')

    @patch('crawlers.ppomppu.crawler.crawler.CrawlerProcess')
    def test_empty_run_is_reported_as_failure(self, process):
        process.return_value.create_crawler.return_value.stats.get_value.return_value = 0
        with self.assertRaisesRegex(RuntimeError, 'without successfully processed items'):
            crawl()

    @patch('crawlers.ppomppu.crawler.crawler.CrawlerProcess')
    def test_run_with_processed_items_succeeds(self, process):
        process.return_value.create_crawler.return_value.stats.get_value.return_value = 1
        crawl()
