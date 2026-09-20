import unittest
from scrapy.http import HtmlResponse
from crawlers.utils.links import absolute_url, product_link


class LinkTests(unittest.TestCase):
    def response(self, html):
        return HtmlResponse('https://coolenjoy.net/bbs/jirum/123', body=html.encode(), encoding='utf-8')

    def test_full_external_text_bypasses_community_tracking_wrapper(self):
        for suffix in ('', '\t<span>1</span>\n회 연결'):
            response=self.response('<a href="/bbs/link2.php?id=1">https://shop.example.com/products/123\t'+suffix+'</a>')
            self.assertEqual(product_link(response,'a'),'https://shop.example.com/products/123')

    def test_real_href_preserves_complete_url_when_label_is_shortened(self):
        response=self.response('<a href="https://shop.example.com/products/123?option=large">https://shop.example.com/prod…</a>')
        self.assertEqual(product_link(response,'a'),'https://shop.example.com/products/123?option=large')

    def test_truncated_text_does_not_replace_an_intermediate_link(self):
        response=self.response('<a href="/bbs/link2.php?id=1">https://shop.example.com/prod...</a>')
        self.assertEqual(product_link(response,'a'),'https://coolenjoy.net/bbs/link2.php?id=1')

    def test_missing_or_unsafe_urls_are_not_persisted(self):
        self.assertEqual(product_link(self.response('<a href="javascript:go()">구매하기</a>'),'a'),'')
        self.assertEqual(absolute_url(None,'https://example.com'),'')
        self.assertEqual(absolute_url('//cdn.example.com/a.jpg','https://example.com'),'https://cdn.example.com/a.jpg')
