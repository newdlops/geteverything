from datetime import timedelta
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from django.db import connection
from django.utils import timezone
from scrapy import Request
from scrapy.exceptions import DropItem
from scrapy.http import HtmlResponse

from crawlers.availability import AvailabilitySpiderMixin, detect_availability, post_key
from crawlers.availability_store import due_deals, record_observation
from crawlers.pipelines import DealPipeline
from gadmin.deals.models import Deal, DealAvailability


URLS = {'arca': 'https://arca.live/b/hotdeal/123', 'fmkorea': 'https://www.fmkorea.com/123',
        'ppomppu': 'https://www.ppomppu.co.kr/zboard/view.php?id=ppomppu&no=123',
        'eomisae': 'https://eomisae.co.kr/fs/123', 'coolnjoy': 'https://coolenjoy.net/bbs/jirum/123'}
HEADINGS = {'arca': '<div class="article-head"><div class="title-row"><div class="title">{}</div></div></div>',
            'fmkorea': '<div class="rd_hd"><h1 class="np_18px">{}</h1></div>',
            'ppomppu': '<div id="topTitle"><h1>{}</h1></div>',
            'eomisae': '<div id="D_"><div class="_hd"><h2><a class="pjax">{}</a></h2></div></div>',
            'coolnjoy': '<h1 id="bo_v_title">{}</h1>'}


def response(site, html='', status=200, url=None):
    request = Request(URLS[site])
    return HtmlResponse(url or request.url, request=request, body=html, status=status, encoding='utf-8')


class DetectionTests(unittest.TestCase):
    def test_all_sites_recognize_active_detail_without_scanning_comments(self):
        for site, heading in HEADINGS.items():
            with self.subTest(site=site):
                html = heading.format('품절가능성, 곧 종료! 마감임박 상품')
                html += '<div class="comment">삭제되었습니다 [품절] 종료</div><div class="listing">[종료] 다른 글</div>'
                self.assertEqual(detect_availability(site, response(site, html))['outcome'], 'active')

    def test_real_arca_and_fmkorea_markers_are_scoped_to_the_open_article(self):
        arca = HEADINGS['arca'].format('콜라').replace('class="title"', 'class="title close-deal"')
        fm = HEADINGS['fmkorea'].format('콜라')+'<div class="rd_body"><div class="hotdeal_var8Y_msg">종료된 핫딜입니다.</div></div>'
        for site, html in [('arca', arca), ('fmkorea', fm)]:
            self.assertEqual(detect_availability(site, response(site, html))['outcome'], 'ended')
        adjacent = HEADINGS['fmkorea'].format('콜라')+'<li><a class="hotdeal_var8Y">다른 글</a></li>'
        self.assertEqual(detect_availability('fmkorea', response('fmkorea', adjacent))['outcome'], 'active')

    def test_explicit_title_labels_and_restock_phrases(self):
        for title in ['[종료] 콜라', '콜라(품절)', '[G마켓] 종료된 행사입니다.']:
            self.assertEqual(detect_availability('coolnjoy', response('coolnjoy', HEADINGS['coolnjoy'].format(title)))['outcome'], 'ended')
        for title in ['(품절풀림) 콜라', '마감임박 상품', '품절가능성', '오늘 종료 예정']:
            self.assertEqual(detect_availability('coolnjoy', response('coolnjoy', HEADINGS['coolnjoy'].format(title)))['outcome'], 'active')

    def test_actual_missing_messages_do_not_include_deleted_comments(self):
        for site, html in [('ppomppu', '<div class="error2">선택하신 게시물이 존재하지 않습니다(1)</div>'),
                           ('coolnjoy', '<div id="validation_check"><p class="cbg">글이 존재하지 않습니다. 글이 삭제되었거나 이동된 경우입니다.</p></div>')]:
            self.assertEqual(detect_availability(site, response(site, html))['outcome'], 'deleted')
        self.assertEqual(detect_availability('fmkorea', response('fmkorea', '<div class="comment">[삭제된 댓글입니다.]</div>'))['outcome'], 'unknown')

    def test_404_requires_confirmation_but_410_is_gone(self):
        self.assertEqual(detect_availability('arca', response('arca', status=404))['outcome'], 'missing')
        self.assertEqual(detect_availability('arca', response('arca', status=410))['outcome'], 'deleted')

    def test_blocked_errors_login_redirect_and_partial_html_are_unknown(self):
        for code in [403, 429, 430, 500, 503]:
            self.assertEqual(detect_availability('arca', response('arca', status=code))['outcome'], 'unknown')
        for code in [200, 404]:
            self.assertEqual(detect_availability('arca', response('arca', '<title>Just a moment...</title>', status=code))['outcome'], 'unknown')
        self.assertEqual(detect_availability('arca', response('arca', status=404, url='https://arca.live/login'))['outcome'], 'unknown')
        self.assertEqual(detect_availability('arca', response('arca', '<p>Removed</p>'))['outcome'], 'unknown')

    def test_response_for_a_different_article_is_not_used(self):
        self.assertEqual(detect_availability('arca', response('arca', status=404, url='https://arca.live/b/hotdeal/456'))['outcome'], 'unknown')
        html = HEADINGS['fmkorea'].format('title')+'<div class="rd" data-docSrl="456"></div>'
        self.assertEqual(detect_availability('fmkorea', response('fmkorea', html))['outcome'], 'unknown')

    def test_recheck_urls_cannot_leave_known_community_or_target_a_list(self):
        for value in ['https://evil.example/b/hotdeal/123', 'http://127.0.0.1/b/hotdeal/123',
                      'https://arca.live:8191/b/hotdeal/123', 'https://user@arca.live/b/hotdeal/123', 'https://arca.live/b/hotdeal']:
            self.assertIsNone(post_key('arca', value))
        self.assertEqual(post_key('fmkorea', 'https://www.fmkorea.com/index.php?document_srl=123&mid=hotdeal'), '123')


class StorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        assert connection.vendor == 'sqlite' and connection.settings_dict['NAME'] == ':memory:'
        # Minimal legacy table: the real status model and ORM execute SQL, without
        # installing unrelated PostgreSQL vector extensions in the unit database.
        with connection.cursor() as cursor:
            cursor.execute('CREATE TABLE deals (id integer PRIMARY KEY, article_id text, is_end bool, community_name text, origin_url text, update_at datetime, price integer, thumbnail text)')
        with connection.schema_editor() as editor:
            editor.create_model(DealAvailability)

    @classmethod
    def tearDownClass(cls):
        with connection.schema_editor() as editor:
            editor.delete_model(DealAvailability)
        with connection.cursor() as cursor:
            cursor.execute('DROP TABLE deals')
        super().tearDownClass()

    def setUp(self):
        self.now = timezone.now()
        with connection.cursor() as cursor:
            cursor.execute('INSERT INTO deals VALUES (1, %s, 0, %s, %s, %s, 12900, %s)',
                ['arca123', 'ARCA', URLS['arca'], self.now-timedelta(days=2), 'https://static.example/image.jpg'])

    def tearDown(self):
        with connection.cursor() as cursor:
            cursor.execute('DELETE FROM deal_availability')
            cursor.execute('DELETE FROM deals')

    def observe(self, outcome, minutes=0):
        return record_observation('arca123', {'outcome': outcome, 'evidence': 'test-'+outcome}, self.now+timedelta(minutes=minutes))

    def test_end_and_delete_keep_price_image_and_history_timestamp(self):
        before = Deal.objects.values('price', 'thumbnail', 'update_at').get(pk=1)
        result = self.observe('ended')
        self.assertEqual(result.state, 'ended')
        self.assertTrue(Deal.objects.values_list('is_end', flat=True).get(pk=1))
        self.assertEqual(Deal.objects.values('price', 'thumbnail', 'update_at').get(pk=1), before)
        self.assertEqual(self.observe('deleted', 20).state, 'deleted')

    def test_two_404_observations_must_be_separated_in_time(self):
        self.observe('missing')
        self.observe('missing', 1)
        self.assertFalse(Deal.objects.values_list('is_end', flat=True).get(pk=1))
        self.assertEqual(self.observe('missing', 30).state, 'deleted')
        self.assertTrue(Deal.objects.values_list('is_end', flat=True).get(pk=1))

    def test_unknown_breaks_missing_confirmation_and_preserves_confirmed_end(self):
        self.observe('missing');self.observe('unknown', 20)
        self.assertEqual(self.observe('missing', 40).missing_count, 1)
        self.observe('ended', 50);self.observe('unknown', 60)
        self.assertTrue(Deal.objects.values_list('is_end', flat=True).get(pk=1))

    def test_valid_reappearance_reopens_a_deal(self):
        self.observe('deleted')
        result = self.observe('active', 60)
        self.assertIsNone(result.ended_at)
        self.assertFalse(Deal.objects.values_list('is_end', flat=True).get(pk=1))

    def test_outdated_observation_is_ignored(self):
        self.observe('ended', 10);self.observe('active', 0)
        self.assertTrue(Deal.objects.values_list('is_end', flat=True).get(pk=1))

    def test_missing_unknown_post_does_not_create_empty_deal(self):
        self.assertIsNone(record_observation('arca999', {'outcome': 'deleted'}))
        self.assertEqual(Deal.objects.count(), 1)

    def test_rechecks_are_bounded_and_confirmation_is_prioritized(self):
        self.observe('missing')
        with connection.cursor() as cursor:
            cursor.execute('INSERT INTO deals VALUES (2, %s, 0, %s, %s, %s, 100, %s)',
                ['arca456', 'ARCA', URLS['arca'].replace('123', '456'), self.now-timedelta(days=1), ''])
        self.assertEqual(due_deals('ARCA', 1, self.now+timedelta(minutes=31))[0]['article_id'], 'arca123')
        self.observe('active', 32)
        self.assertEqual([row['article_id'] for row in due_deals('ARCA', 5, self.now+timedelta(minutes=33))], ['arca456'])

    def test_terminal_status_item_bypasses_price_and_date_parsing(self):
        pipeline = DealPipeline();pipeline.article_id_prefix = 'arca'
        pipeline.get_defaults = Mock(side_effect=AssertionError('must not parse incomplete content'))
        item = {'article_id': '123', '_status_only': True, '_availability': {'outcome': 'deleted'}}
        with self.assertRaises(DropItem):
            pipeline.process_item(item, None)
        self.assertTrue(Deal.objects.values_list('is_end', flat=True).get(pk=1))


class RequestTests(unittest.TestCase):
    def setUp(self):
        self.spider = AvailabilitySpiderMixin();self.spider.availability_site = 'arca'
        self.spider.detail_parse = Mock(return_value=iter([{'article_id': '123', 'subject': '콜라'}]))

    def test_normal_and_status_only_requests_use_the_same_detector(self):
        req = self.spider.deal_request(URLS['arca'], {'article_id': '123'}, status_only=True)
        self.assertEqual(req.meta['handle_httpstatus_list'], [404, 410])
        result = list(self.spider.parse_deal(HtmlResponse(req.url, request=req, status=404), req.cb_kwargs['data']))
        self.assertEqual(result[0]['_availability']['outcome'], 'missing')
        self.spider.detail_parse.assert_not_called()

    def test_fmkorea_query_link_is_not_embedded_inside_document_srl(self):
        from crawlers.fmkorea.spider.spider import FmKoreaSpider
        html = '<div class="fm_best_widget"><li><h3 class="title" data-original-title="콜라"><a href="/index.php?mid=hotdeal&amp;document_srl=123">콜라</a></h3></li></div>'
        page = response('fmkorea', html)
        page.request.meta['cookiejar'] = 1
        request, = list(FmKoreaSpider().parse(page))
        self.assertEqual(request.url, 'https://www.fmkorea.com/?mid=hotdeal&sort_index=&order_type=desc&document_srl=123&listStyle=webzine&cpage=1')
        self.assertEqual(post_key('fmkorea', request.url), '123')
        self.assertEqual(request.cb_kwargs['data']['origin_url'], 'https://www.fmkorea.com/index.php?mid=hotdeal&document_srl=123')

    def test_all_site_start_methods_enqueue_bounded_rechecks(self):
        from crawlers.arca.spider.spider import ArcaSpider
        from crawlers.fmkorea.spider.spider import FmKoreaSpider
        from crawlers.ppomppu.spider.spider import PpomppuSpider
        from crawlers.eomisae.spider.spider import EomisaeSpider
        from crawlers.coolnjoy.spider import CoolNJoySpider
        for cls in [ArcaSpider, FmKoreaSpider, PpomppuSpider, EomisaeSpider, CoolNJoySpider]:
            with self.subTest(cls=cls.__name__), patch.object(cls, 'availability_rechecks', return_value=iter([])) as checks:
                list(cls().start_requests());checks.assert_called_once()

    def test_invalid_environment_limit_is_capped_and_proxy_is_preserved(self):
        self.spider.availability_site = 'ppomppu';self.spider.request_meta = lambda n: {'proxy': 'http://127.0.0.1:18888', 'cookiejar': n}
        with patch.dict(os.environ, {'CRAWLER_STATUS_RECHECK_LIMIT': '999'}), patch('crawlers.availability_store.due_deals', return_value=[{'article_id':'ppompu123','origin_url':URLS['ppomppu']}]) as query:
            requests = list(self.spider.availability_rechecks())
        query.assert_called_once_with('PPOMPPU', 5)
        self.assertEqual(requests[0].meta['proxy'], 'http://127.0.0.1:18888')
