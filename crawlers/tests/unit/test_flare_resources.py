from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import requests
from scrapy import Request
from scrapy.downloadermiddlewares.cookies import CookiesMiddleware
from scrapy.http import HtmlResponse
from scrapy.settings import Settings
from scrapy.utils.conf import build_component_list
from tldextract import TLDExtract

from crawlers.arca.spider.spider import ArcaSpider
from crawlers.middlewares.flare_solver_middleware import FlareSolverrMiddleware


class FlareResourceTests(TestCase):
    def setUp(self):
        self.spider = SimpleNamespace(name='arca_spider', logger=Mock())
        self.middleware = FlareSolverrMiddleware('http://127.0.0.1:8191/v1', stats=Mock())
        self.middleware._api = Mock(side_effect=self.reply)
        self.addCleanup(self.middleware.client.close)
        suffixes = patch('scrapy.downloadermiddlewares.cookies._split_domain',
                         TLDExtract(suffix_list_urls=(), cache_dir=None, include_psl_private_domains=True))
        suffixes.start()
        self.addCleanup(suffixes.stop)

    def request(self, page=1):
        return Request(f'https://arca.live/b/hotdeal?p={page}', meta={'use_flaresolverr': True, 'cookiejar': page})

    def reply(self, payload, timeout):
        return {'status': 'ok', 'solution': {'url': payload.get('url'), 'status': 200,
            'response': '<html>cleared page</html>', 'userAgent': 'test-browser',
            'cookies': [{'name': 'cf_clearance', 'value': 'test-clearance'}]}}

    def test_actual_spider_order_sends_cached_cookies_before_downloading(self):
        self.middleware.process_request(self.request(), self.spider)
        self.middleware._api.reset_mock()
        request = self.request(2)
        settings = Settings()
        settings.setdict(ArcaSpider.custom_settings, priority='spider')
        cookies = CookiesMiddleware()
        for component in build_component_list(settings.getwithbase('DOWNLOADER_MIDDLEWARES')):
            if component is FlareSolverrMiddleware:
                self.assertIsNone(self.middleware.process_request(request, self.spider))
            elif component == 'scrapy.downloadermiddlewares.cookies.CookiesMiddleware':
                cookies.process_request(request, self.spider)
        self.assertIn(b'cf_clearance=test-clearance', request.headers[b'Cookie'])
        self.assertEqual(request.headers[b'User-Agent'], b'test-browser')
        self.middleware._api.assert_not_called()

    def test_browser_is_reused_and_document_released_without_losing_result(self):
        first = self.request()
        response = self.middleware.process_request(first, self.spider)
        self.assertIn(b'cleared page', response.body)
        second = self.request(2)
        self.middleware.process_request(second, self.spider)
        self.middleware.process_response(second, HtmlResponse(second.url, status=403), self.spider)
        calls = [c.args[0] for c in self.middleware._api.call_args_list]
        renders = [p for p in calls if p.get('url', '').startswith('https://')]
        parked = [p for p in calls if p.get('url') == 'about:blank']
        self.assertEqual(len(renders), 2)
        self.assertEqual({p['session'] for p in renders + parked}, {renders[0]['session']})
        self.assertEqual(len(parked), 2)
        self.middleware.spider_closed(self.spider)
        self.assertEqual(self.middleware._api.call_args.args[0], {'cmd': 'sessions.destroy', 'session': renders[0]['session']})
        self.assertFalse(self.middleware.sessions)

    def test_browser_bound_clearance_does_not_repeat_failed_http_on_every_page(self):
        self.middleware.process_request(self.request(), self.spider)
        for page in (2, 3):
            request = self.request(page)
            self.assertIsNone(self.middleware.process_request(request, self.spider))
            self.middleware.process_response(request, HtmlResponse(request.url, status=403), self.spider)
        self.assertIsInstance(self.middleware.process_request(self.request(4), self.spider), HtmlResponse)
        self.assertEqual(self.middleware.http_failures['arca.live'], 2)

    def test_http_success_uses_no_browser(self):
        request = self.request()
        response = HtmlResponse(request.url, status=200, body=b'normal response')
        self.assertIs(self.middleware.process_response(request, response, self.spider), response)
        self.middleware._api.assert_not_called()

    def test_backend_failure_has_bounded_retry_and_is_not_reported_as_success(self):
        self.middleware._api.side_effect = requests.Timeout()
        request = self.request()
        response = self.middleware.process_request(request, self.spider)
        self.assertEqual(response.status, 503)
        self.assertEqual(request.meta['max_retry_times'], 1)
        calls = self.middleware._api.call_count
        self.assertIs(self.middleware.process_response(request, response, self.spider), response)
        self.assertEqual(calls, self.middleware._api.call_count)

    def test_failed_parking_closes_browser_but_preserves_downloaded_content(self):
        self.middleware._api.side_effect = [self.reply({}, 0), requests.Timeout(), {'status': 'ok'}]
        response = self.middleware.process_request(self.request(), self.spider)
        self.assertEqual(response.status, 200)
        self.assertIn(b'cleared page', response.body)
        self.assertEqual(self.middleware._api.call_args.args[0]['cmd'], 'sessions.destroy')
        self.assertFalse(self.middleware.sessions)

    def test_empty_browser_document_is_failure_and_unmarked_requests_are_ignored(self):
        self.middleware._api.return_value = {'status': 'ok', 'solution': {'response': ''}}
        self.middleware._api.side_effect = None
        self.assertEqual(self.middleware.process_request(self.request(), self.spider).status, 503)
        self.middleware._api.reset_mock()
        self.assertIsNone(self.middleware.process_request(Request('https://example.com'), self.spider))
        self.middleware._api.assert_not_called()

    def test_process_replacement_reuses_its_session_without_touching_other_spiders(self):
        replacement = FlareSolverrMiddleware('http://127.0.0.1:8191/v1')
        self.addCleanup(replacement.client.close)
        first = self.middleware._session('arca.live', self.spider)
        self.assertEqual(first, replacement._session('arca.live', self.spider))
        self.assertNotEqual(first, replacement._session('other.example', self.spider))
