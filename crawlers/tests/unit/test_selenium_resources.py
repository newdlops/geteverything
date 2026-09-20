import os
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, call, patch

from scrapy import Request
from scrapy.settings import Settings
from selenium.common import WebDriverException

from crawlers.middlewares.selenium_middleware import SeleniumMiddleware


class SeleniumResourceTests(TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {
            "SELENIUM_BLOCK_MEDIA": "1", "SELENIUM_IDLE_BLANK_PAGE": "1",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.spider = SimpleNamespace(
            name="test_spider", logger=Mock(), crawler=SimpleNamespace(settings=Settings()),
        )
        self.middleware = SeleniumMiddleware()
        self.driver = Mock()
        self.middleware.driver = self.driver
        self.middleware._driver_proxy = None
        self.middleware._handle_cloudflare_challenge = Mock()
        self.request = Request("https://example.com/deal/1", meta={"cookiejar": 1})
        self.driver.page_source = "<html><body>Deal content</body></html>"
        self.driver.current_url = self.request.url
        self.driver.get_cookies.return_value = [{"name": "session", "value": "test-session"}]

    def test_releases_document_after_capturing_html_and_cookies_and_reuses_browser(self):
        def navigate(url):
            if url == "about:blank":
                self.driver.page_source = "<html><body></body></html>"
                self.driver.current_url = url

        self.driver.get.side_effect = navigate
        response = self.middleware.process_request(self.request, self.spider)

        self.assertIn(b"Deal content", response.body)
        self.assertEqual(response.url, self.request.url)
        self.assertEqual(self.middleware._cookiejars["1"]["example.com"], [
            {"name": "session", "value": "test-session"},
        ])
        self.assertEqual(self.driver.get.call_args_list, [
            call(self.request.url), call("about:blank"),
        ])
        self.assertIs(self.middleware.driver, self.driver)
        self.driver.quit.assert_not_called()

    def test_releases_document_when_rendering_fails(self):
        self.driver.get.side_effect = [WebDriverException("navigation failed"), None]
        with self.assertRaisesRegex(WebDriverException, "navigation failed"):
            self.middleware.process_request(self.request, self.spider)
        self.assertEqual(self.driver.get.call_args_list, [
            call(self.request.url), call("about:blank"),
        ])

    def test_closes_browser_if_releasing_document_fails_without_losing_response(self):
        self.driver.get.side_effect = [None, WebDriverException("cleanup failed")]
        response = self.middleware.process_request(self.request, self.spider)
        self.assertIn(b"Deal content", response.body)
        self.driver.quit.assert_called_once()
        self.assertIsNone(self.middleware.driver)

    def test_idle_cleanup_can_be_disabled_by_environment(self):
        with patch.dict(os.environ, {"SELENIUM_IDLE_BLANK_PAGE": "0"}):
            response = self.middleware.process_request(self.request, self.spider)
        self.assertIn(b"Deal content", response.body)
        self.driver.get.assert_called_once_with(self.request.url)

    def test_spider_setting_overrides_environment_for_idle_cleanup(self):
        self.spider.crawler.settings.set("SELENIUM_IDLE_BLANK_PAGE", True)
        with patch.dict(os.environ, {"SELENIUM_IDLE_BLANK_PAGE": "0"}):
            self.middleware.process_request(self.request, self.spider)
        self.assertEqual(self.driver.get.call_args_list[-1], call("about:blank"))

    def test_media_controls_can_be_disabled_without_disabling_cookie_support(self):
        for enabled in (True, False):
            with (
                self.subTest(enabled=enabled),
                patch.dict(os.environ, {"SELENIUM_BLOCK_MEDIA": str(int(enabled))}),
                patch.object(self.middleware, "_copy_chromedriver", return_value=None),
                patch.object(self.middleware, "_resolve_chrome_binary", return_value=None),
                patch("crawlers.middlewares.selenium_middleware.os.makedirs"),
                patch("crawlers.middlewares.selenium_middleware.stealth"),
                patch("crawlers.middlewares.selenium_middleware.uc.Chrome") as chrome,
            ):
                self.middleware._create_driver(self.spider, proxy=None)
                options = chrome.call_args.kwargs["options"]
                prefs = options.experimental_options.get("prefs", {})
                self.assertEqual(prefs.get("profile.managed_default_content_settings.images"),
                                 2 if enabled else None)
                commands = chrome.return_value.execute_cdp_cmd.call_args_list
                self.assertIn(call("Network.enable", {}), commands)
                blocked = [c for c in commands if c.args[0] == "Network.setBlockedURLs"]
                self.assertEqual(bool(blocked), enabled)
                if enabled:
                    self.assertNotIn("*.js", blocked[0].args[1]["urls"])
                    self.assertNotIn("*.css", blocked[0].args[1]["urls"])

    def test_verbose_browser_cannot_block_on_undrained_output_pipes(self):
        with tempfile.TemporaryDirectory(prefix="browser test '") as directory:
            wrapper = self.middleware._quiet_browser_binary(sys.executable, directory)
            script = "import os,sys; assert sys.argv[1] == 'literal $(value)'; os.write(1,b'x'*2097152); os.write(2,b'x'*2097152)"
            process = subprocess.Popen([wrapper, '-c', script, 'literal $(value)'],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                self.assertEqual(process.wait(timeout=5), 0)
                self.assertEqual(process.communicate(), (b'', b''))
            finally:
                if process.poll() is None:
                    process.kill();process.wait(timeout=3)
            self.middleware._destroy_driver(self.spider)
            self.assertFalse(os.path.exists(wrapper))
