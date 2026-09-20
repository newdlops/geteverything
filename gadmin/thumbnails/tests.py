from io import BytesIO
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from .discovery import discover_images, discover_post_images, encode_thumbnail
from .fetch import Download, ThumbnailError, fetch, normalize_url, product_url, public_address
from .store import Store, TTL_SECONDS
from .worker import Deals, collect, run
from .requests import Requests


def raster(size=(800, 600), mode='RGB'):
    stream = BytesIO()
    Image.new(mode, size, 'red').save(stream, format='PNG')
    return stream.getvalue()


class DiscoveryTests(unittest.TestCase):
    def test_community_recovery_only_uses_supported_article_body(self):
        html = '''<meta property="og:image" content="/wrong.jpg"><img src="/nav.jpg">
        <div class="view-content fr-view"><img src="/logo.png">
        <div class="comment"><img src="/reply.jpg"></div>
        <img data-src="//cdn.example.com/goods.jpg" src="/loading.gif"></div>'''
        found = discover_post_images(html, 'https://coolenjoy.net/bbs/jirum/1')
        self.assertEqual([item.url for item in found], ['https://cdn.example.com/goods.jpg'])
        self.assertEqual(discover_post_images(html, 'https://coolenjoy.net.evil.example/'), [])

    def test_article_product_caption_beats_repeated_first_purchase_coupon(self):
        html = '''<div class="view-content fr-view"><p><img src="/first.png"></p>
        <p><img src="/case.png"></p><p>North XL 컴퓨터 케이스</p>
        <p><img src="/memory.png"></p><p>클레브 CRAS RGB 메모리</p>
        <p>첫구매 회원이라면 10% 중복쿠폰!<img src="/first.png"></p></div>'''
        images = discover_post_images(html, 'https://coolenjoy.net/bbs/jirum/1', 'CRAS RGB 메모리')
        self.assertEqual(images[0].url, 'https://coolenjoy.net/memory.png')
        self.assertFalse(any(item.url.endswith('first.png') for item in images))

    def test_product_beats_logo_metadata_and_recommendations(self):
        html = '''<meta property="og:image" content="/logo.png"><script type="application/ld+json">
        {"@graph":[{"@type":"Organization","image":"/company.jpg"},
        {"@type":"Product","name":"좋은 무선 키보드","image":{"contentUrl":"//cdn.example.com/keyboard.jpg"},
        "isRelatedTo":{"@type":"Product","image":"/wrong.jpg"}}]}</script>
        <img class="product-image" src="/body.jpg" width="600" height="600">'''
        values = discover_images(html, 'https://shop.example.com/p/1', '무선 키보드')
        self.assertEqual(values[0].url, 'https://cdn.example.com/keyboard.jpg')
        self.assertEqual(values[0].evidence, 'product_json_ld')
        self.assertFalse(any(word in item.url for item in values for word in ('logo', 'company', 'wrong')))

    def test_main_product_name_ranks_before_other_products(self):
        html = '<script type="application/ld+json">' + json.dumps([
            {'@type': 'Product', 'name': '신발', 'image': '/shoes.jpg'},
            {'@type': 'Product', 'name': '맥북 노트북', 'image': ['/laptop.jpg']},
        ]) + '</script>'
        self.assertTrue(discover_images(html, 'https://shop.example.com/', '맥북 노트북')[0].url.endswith('laptop.jpg'))

    def test_lazy_body_candidates_exclude_navigation_and_small_images(self):
        html = '''<nav><img class="product" src="/nav.jpg"></nav>
        <img class="product" width="24" src="/small.jpg"><img class="gallery" data-src="/main.jpg">
        <img class="banner" src="/ad.jpg"><img src="/unrelated.jpg">'''
        values = discover_images(html, 'https://shop.example.com/x', '')
        self.assertEqual([item.url for item in values], ['https://shop.example.com/main.jpg'])

    def test_malformed_json_and_relative_metadata(self):
        values = discover_images('<script type="application/ld+json">bad json</script><meta property="og:image" content="../photo.jpg">', 'https://shop.example.com/products/1', '')
        self.assertEqual(values[0].url, 'https://shop.example.com/photo.jpg')

    def test_transparency_aspect_size_and_format_are_normalized(self):
        data, size = encode_thumbnail(raster(mode='RGBA'))
        self.assertEqual(size, (480, 360))
        with Image.open(BytesIO(data)) as image:
            self.assertEqual((image.mode, image.format), ('RGB', 'JPEG'))
            self.assertEqual(dict(image.getexif()), {})

    def test_html_tracking_pixels_and_extreme_aspect_are_rejected(self):
        for raw in (b'<html>Forbidden</html>', raster((1, 1)), raster((2000, 100))):
            with self.subTest(length=len(raw)), self.assertRaises(ThumbnailError):
                encode_thumbnail(raw)


class FetchTests(unittest.TestCase):
    @patch('gadmin.thumbnails.fetch.public_address', return_value='93.184.216.34')
    @patch('gadmin.thumbnails.fetch.urllib3.HTTPSConnectionPool')
    def test_identifier_redirect_does_not_download_the_product_page(self, pool, resolve):
        target = 'https://smartstore.naver.com/shop/products/123'
        pool.return_value.request.return_value = Mock(status=302, headers={'Location': target})
        result = fetch('https://naver.me/short', limit=100, deadline=time.monotonic()+10,
                       stop_at=lambda url: url == target)
        self.assertEqual((result.url, result.body), (target, b''))
        self.assertEqual(pool.return_value.request.call_count, 1)
        self.assertEqual(resolve.call_count, 1)

    @patch('gadmin.thumbnails.fetch.public_address')
    def test_malformed_hostname_is_rejected_before_dns_instead_of_crashing_batch(self, resolve):
        for host in ('x'*64 + '.example.com', 'shop..example.com', 'bad host.example.com'):
            with self.subTest(host=host):
                self.assertEqual(normalize_url('https://' + host + '/p/1'), '')
                with self.assertRaises(ThumbnailError):
                    fetch('https://' + host + '/p/1', limit=100, deadline=time.monotonic()+1)
        resolve.assert_not_called()

    def test_url_validation_and_affiliate_unwrap(self):
        self.assertEqual(product_url('https://track.example.com/?url=https%3A%2F%2Fshop.example.com%2Fp%2F1'), 'https://shop.example.com/p/1')
        for url in ('file:///etc/passwd', 'http://user:password@example.com/', 'https://example.com:9999/a', 'javascript:alert(1)'):
            self.assertEqual(normalize_url(url), '')

    @patch('gadmin.thumbnails.fetch.socket.getaddrinfo')
    def test_private_mixed_dns_and_metadata_addresses_are_rejected(self, resolve):
        for addresses in (['127.0.0.1'], ['169.254.169.254'], ['10.0.0.1'], ['::1'], ['93.184.216.34', '192.168.0.1']):
            resolve.return_value = [(2, 1, 6, '', (ip, 443)) for ip in addresses]
            with self.assertRaises(ThumbnailError):
                public_address('shop.example.com', 443)

    @patch('gadmin.thumbnails.fetch.public_address', return_value='93.184.216.34')
    @patch('gadmin.thumbnails.fetch.urllib3.HTTPSConnectionPool')
    def test_tls_and_connection_use_the_validated_ip(self, pool, _resolve):
        response = Mock(status=200, headers={'Content-Type':'image/jpeg'})
        response.read.side_effect = [b'abc', b'']
        pool.return_value.request.return_value = response
        result = fetch('https://shop.example.com/a', limit=10, deadline=time.monotonic()+10)
        self.assertEqual(result.body, b'abc')
        self.assertEqual(pool.call_args.args, ('93.184.216.34', 443))
        self.assertEqual(pool.call_args.kwargs['server_hostname'], 'shop.example.com')
        self.assertEqual(pool.call_args.kwargs['assert_hostname'], 'shop.example.com')
        self.assertFalse(pool.return_value.request.call_args.kwargs['redirect'])

    @patch('gadmin.thumbnails.fetch.public_address', return_value='93.184.216.34')
    @patch('gadmin.thumbnails.fetch.urllib3.HTTPSConnectionPool')
    def test_redirect_to_private_destination_is_checked_again(self, pool, resolve):
        pool.return_value.request.return_value = Mock(status=302, headers={'Location':'http://127.0.0.1/private'})
        resolve.side_effect = ['93.184.216.34', ThumbnailError('non_public_address')]
        with self.assertRaisesRegex(ThumbnailError, 'non_public'):
            fetch('https://shop.example.com/', limit=100, deadline=time.monotonic()+10)
        self.assertEqual(resolve.call_count, 2)

    @patch('gadmin.thumbnails.fetch.public_address', return_value='93.184.216.34')
    @patch('gadmin.thumbnails.fetch.urllib3.HTTPSConnectionPool')
    def test_oversized_stream_without_length_is_bounded(self, pool, _resolve):
        response = Mock(status=200, headers={})
        response.read.return_value = b'123456'
        pool.return_value.request.return_value = response
        with self.assertRaisesRegex(ThumbnailError, 'too_large'):
            fetch('https://shop.example.com/', limit=5, deadline=time.monotonic()+10)
        response.close.assert_called_once()


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch('gadmin.thumbnails.store.shutil.disk_usage', return_value=Mock(free=10*1024**3)))
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.clock = 1789574400
        self.store = Store(self.temporary.name, 'http://static.example.com:8001/media/thumbnails/', now=lambda:self.clock)
        self.addCleanup(self.store.db.close)
        self.row = {'id':12, 'subject':'무선 키보드', 'shop_url_1':'https://shop.example.com/p/1',
                    'shop_url_2':None, 'origin_url':'https://community.example.com/posts/1',
                    'thumbnail':'https://community.example.com/fallback.jpg'}
        self.job = self.store.enqueue(self.row)

    def fake_deals(self):
        deals = Deals.__new__(Deals)
        deals.clear, deals.publish = Mock(), Mock(return_value=1)
        return deals

    def test_empty_thumbnail_is_recovered_from_original_post_when_shop_is_blocked(self):
        row = {**self.row, 'id':13, 'thumbnail':'', 'origin_url':'https://coolenjoy.net/bbs/jirum/1'}
        def download(url, **kwargs):
            if url.startswith('https://shop.'):
                raise ThumbnailError('http_403')
            if '/bbs/' in url:
                return Download(url, b'<div class="view-content fr-view"><img src="/goods.jpg"></div>', 'text/html')
            return Download(url, raster(), 'image/png')
        job = collect(self.store.enqueue(row), self.store, downloader=download)
        self.assertEqual(job['evidence'], 'community_body_v2')
        self.assertEqual(job['status'], 'fallback')
        self.assertEqual(job['expires_at'], self.clock + TTL_SECONDS)

    def test_missing_or_truncated_static_file_is_requeued_even_when_db_url_matches(self):
        for missing in (True, False):
            with self.subTest(missing=missing):
                job = self.store.save_image(self.store.get(12), b'jpeg-test', (200,200), 'product_metadata')
                path = self.store.path(job['object_key'])
                path.unlink() if missing else path.write_bytes(b'')
                deals = self.fake_deals()
                current = deals.reconcile(self.store, {**self.row, 'thumbnail':self.store.url(job)})
                self.assertEqual(current['status'], 'pending')
                self.assertEqual(current['attempts'], 0)
                self.assertEqual(current['object_key'], '')
                deals.publish.assert_not_called()

    def test_backfill_preserves_valid_asset_and_original_expiry(self):
        job = self.store.save_image(self.job, b'jpeg-test', (200,200), 'product_metadata')
        self.clock += 3600
        deals = self.fake_deals()
        job = deals.reconcile(self.store, self.row)
        self.assertFalse(self.store.queue_backfill(job, 'pass-1'))
        self.assertEqual(self.store.get(12)['expires_at'], job['expires_at'])
        deals.publish.assert_called_once_with(job, self.store.url(job))

    def test_backfill_replay_does_not_reset_exhausted_retries(self):
        for _ in range(3):
            self.store.fail(self.store.get(12), 'http_403')
        self.assertTrue(self.store.queue_backfill(self.store.get(12), 'pass-1'))
        for _ in range(3):
            self.store.fail(self.store.get(12), 'http_403')
        self.assertFalse(self.store.queue_backfill(self.store.get(12), 'pass-1'))
        self.assertEqual(self.store.get(12)['attempts'], 3)

    def test_backfill_cursor_resumes_and_advances_to_all_existing_posts(self):
        state = {'id':'pass-1', 'phase':'missing', 'ceiling':12, 'cursor':13, 'scanned':0}
        self.store.set_meta('backfill', state)
        deals = self.fake_deals()
        deals.backfill_rows = Mock(side_effect=[[self.row], [], [{**self.row, 'id':11}], []])
        deals.backfill(self.store)
        self.assertEqual(self.store.meta('backfill')['cursor'], 12)
        deals.backfill(self.store)
        self.assertEqual(self.store.meta('backfill')['phase'], 'all')
        self.assertEqual(self.store.meta('backfill')['cursor'], 13)
        deals.backfill(self.store)
        self.assertEqual(self.store.meta('backfill')['cursor'], 11)
        deals.backfill(self.store)
        self.assertEqual(self.store.meta('backfill')['phase'], 'draining')
        self.assertEqual(self.store.backfill_status()['jobs'], 2)

    def test_backfill_discovery_is_bounded_by_unattempted_queue(self):
        self.store.set_meta('backfill', {'id':'pass-1', 'phase':'missing', 'ceiling':100, 'cursor':101})
        for deal_id in range(50):
            job = self.store.enqueue({**self.row, 'id':deal_id})
            self.store.queue_backfill(job, 'pass-1')
        deals = self.fake_deals()
        deals.backfill_rows = Mock()
        deals.backfill(self.store)
        deals.backfill_rows.assert_not_called()
        self.assertEqual(self.store.meta('backfill')['cursor'], 101)

    def test_new_crawls_take_priority_over_historical_jobs(self):
        for deal_id in range(10, 13):
            self.store.enqueue({**self.row, 'id':deal_id})
        old = self.store.enqueue({**self.row, 'id':1})
        self.store.queue_backfill(old, 'pass-1')
        self.assertEqual([job['deal_id'] for job in self.store.due(4)], [12,11,10,1])
        self.assertEqual([job['deal_id'] for job in self.store.due(4, live_only=True)], [12,11,10])

    def test_crawl_request_promotes_backfill_without_resetting_retries(self):
        self.store.queue_backfill(self.job, 'pass-1')
        self.store.fail(self.store.get(12), 'http_403')
        job = self.store.get(12)
        self.store.request_live(job, 100, self.clock)
        self.store.request_live(self.store.get(12), 101, self.clock + 1)
        current = self.store.get(12)
        self.assertEqual(current['backfill_run'], 'pass-1')
        self.assertEqual(current['attempts'], 1)
        self.assertEqual(current['next_at'], job['next_at'])
        self.clock += 400
        self.assertEqual([job['deal_id'] for job in self.store.due(live_only=True)], [12])

    def test_request_replay_preserves_asset_and_ttl(self):
        job = self.store.save_image(self.job, b'jpeg-test', (200,200), 'product_metadata')
        self.store.request_live(job, 100, self.clock)
        self.clock += 3600
        self.store.request_live(self.store.get(12), 99, self.clock)
        current = self.store.get(12)
        self.assertEqual(current['live_revision'], 100)
        self.assertEqual(current['expires_at'], job['expires_at'])
        self.assertEqual(current['object_key'], job['object_key'])
        self.assertEqual(self.store.due(), [])

    def test_one_unexpected_data_error_does_not_block_next_post(self):
        self.store.enqueue({**self.row, 'id':11})
        def collect_one(job, store):
            if job['deal_id'] == 12:
                raise UnicodeError('bad third-party input')
            return store.save_image(job, b'jpeg-test', (200,200), 'product_metadata')
        with patch('gadmin.thumbnails.worker.collect', side_effect=collect_one):
            stats = run(self.store, Mock(), batch=2, maintenance=False)
        self.assertEqual((stats['failed'], stats['collected']), (1,1))
        self.assertEqual(self.store.get(12)['error'], 'unexpected_UnicodeError')
        self.assertEqual(self.store.get(12)['attempts'], 1)
        self.assertTrue(self.store.has_asset(self.store.get(11)))

    def test_new_request_arriving_during_backfill_runs_before_next_historical_item(self):
        for identity in (11,12):
            job = self.store.enqueue({**self.row, 'id':identity})
            self.store.queue_backfill(job, 'pass-1')
        requests = Mock()
        def insert_new(store, deals):
            job = store.enqueue({**self.row, 'id':99})
            store.request_live(job, 100, self.clock)
            return 1
        calls = 0
        def drain(store, deals):
            nonlocal calls
            calls += 1
            return insert_new(store, deals) if calls == 2 else 0
        requests.drain.side_effect = drain
        seen = []
        def collect_one(job, store):
            seen.append(job['deal_id'])
            return store.save_image(job, b'jpeg-test', (200,200), 'product_metadata')
        with patch('gadmin.thumbnails.worker.collect', side_effect=collect_one):
            run(self.store, Mock(), batch=3, requests=requests, maintenance=False)
        self.assertEqual(seen, [12,99,11])

    def test_stop_does_not_begin_another_download(self):
        with patch('gadmin.thumbnails.worker.collect') as download:
            run(self.store, Mock(), maintenance=False, should_stop=lambda: True)
        download.assert_not_called()

    def test_request_is_not_acknowledged_if_local_persistence_fails(self):
        requests = Requests.__new__(Requests)
        requests.connection = Mock()
        cursor = Mock()
        requests.connection.cursor.return_value.__enter__ = Mock(return_value=cursor)
        requests.connection.cursor.return_value.__exit__ = Mock(return_value=False)
        cursor.fetchall.return_value = [(12, 100, datetime.fromtimestamp(self.clock, timezone.utc))]
        deals = self.fake_deals()
        deals.lookup = Mock(return_value=self.row)
        with patch.object(self.store, 'request_live', side_effect=RuntimeError('disk failure')):
            with self.assertRaises(RuntimeError):
                requests.drain(self.store, deals)
        self.assertEqual(cursor.execute.call_count, 1)

    def test_scan_finished_is_not_complete_until_retries_and_publishing_finish(self):
        self.store.set_meta('backfill', {'id':'pass-1', 'phase':'draining'})
        self.store.queue_backfill(self.job, 'pass-1')
        self.assertEqual(self.store.backfill_status()['phase'], 'draining')
        job = self.store.save_image(self.store.get(12), b'jpeg-test', (200,200), 'product_metadata')
        self.assertEqual(self.store.backfill_status()['phase'], 'draining')
        self.store.mark_published(job)
        self.assertEqual(self.store.backfill_status()['phase'], 'complete')
        self.assertEqual(self.store.backfill_status()['saved'], 1)

    def test_failed_publish_precondition_does_not_mark_asset_published(self):
        self.store.save_image(self.job, b'jpeg-test', (200,200), 'product_metadata')
        deals = Mock()
        deals.publish.return_value = 0
        run(self.store, deals)
        self.assertEqual(self.store.get(12)['published'], 0)

    def test_identical_image_quality_review_keeps_original_url_and_expiry(self):
        job = self.store.save_image(self.job, b'jpeg-test', (200,200), 'community_body')
        self.clock += 1200
        result = self.store.save_image(job, b'jpeg-test', (200,200), 'community_body_v2')
        self.assertEqual(result['object_key'], job['object_key'])
        self.assertEqual(result['expires_at'], job['expires_at'])
        self.assertEqual(result['evidence'], 'community_body_v2')

    def test_community_quality_review_is_bounded_and_rereads_original_article(self):
        self.store.save_image(self.job, b'old-coupon', (200,200), 'community_body')
        self.store.review_community_images()
        self.store.fail(self.store.get(12), 'http_403')
        self.store.review_community_images()
        self.assertEqual(self.store.get(12)['attempts'], 1)
        def download(url, **kwargs):
            if '/bbs/' in url:
                return Download(url, b'<div class="view-content fr-view"><p><img src="/goods.jpg"></p></div>', 'text/html')
            if url.endswith('/goods.jpg'):
                return Download(url, raster(), 'image/png')
            raise ThumbnailError('http_403')
        job = self.store.enqueue({**self.row, 'origin_url':'https://coolenjoy.net/bbs/jirum/1'})
        result = collect(job, self.store, downloader=download)
        self.assertEqual(result['evidence'], 'community_body_v2')
        self.assertNotEqual(result['object_key'], job['object_key'])

    def test_product_image_is_selected_and_persisted_with_exact_ttl(self):
        def download(url, **kwargs):
            if '/p/1' in url:
                return Download(url, b'<meta property="og:image" content="/product.jpg">', 'text/html')
            return Download(url, raster(), 'image/png')
        job = collect(self.job, self.store, downloader=download)
        self.assertEqual(job['evidence'], 'product_metadata')
        self.assertEqual(job['expires_at'], self.clock + TTL_SECONDS)
        self.assertTrue(self.store.path(job['object_key']).is_file())
        self.assertTrue(self.store.url(job).startswith(self.store.base_url))
        self.assertEqual(self.store.due(), [])

    def test_blocked_product_uses_stored_community_fallback_without_extending_ttl(self):
        def download(url, **kwargs):
            if url.startswith('https://shop.'):
                raise ThumbnailError('http_403')
            return Download(url, raster((100, 100)), 'image/png')
        job = collect(self.job, self.store, downloader=download)
        expires = job['expires_at']
        key = job['object_key']
        self.clock += 3600
        again = collect(job, self.store, downloader=download)
        self.assertEqual(again['expires_at'], expires)
        self.assertEqual(again['object_key'], key)
        self.assertEqual(again['evidence'], 'community_fallback')

    def test_retry_limit_and_duplicate_recrawl(self):
        for _ in range(3):
            self.store.fail(self.store.get(12), 'http_403')
            self.clock += 7200
            self.store.enqueue(self.row)
        self.assertEqual(self.store.due(), [])
        self.assertEqual(self.store.get(12)['attempts'], 3)

    def test_new_product_url_resets_the_job(self):
        self.store.fail(self.job, 'http_403')
        self.store.enqueue({**self.row, 'shop_url_1':'https://shop.example.com/p/2'})
        self.assertEqual(self.store.get(12)['attempts'], 0)
        self.assertEqual(self.store.get(12)['payload']['shop_url_1'], 'https://shop.example.com/p/2')

    def test_changed_product_does_not_restore_previous_image(self):
        job = self.store.save_image(self.job, b'jpeg-test', (200,200), 'product_metadata')
        deals = Deals.__new__(Deals)
        deals.clear, deals.publish = Mock(), Mock()
        deals.reconcile(self.store, {**self.row, 'thumbnail':self.store.url(job),
                                     'shop_url_1':'https://shop.example.com/p/2'})
        deals.clear.assert_called_once_with(job, self.store.url(job))
        deals.publish.assert_not_called()
        self.assertEqual(self.store.get(12)['object_key'], '')

    def test_changed_affiliate_token_keeps_asset_and_refreshes_publish_precondition(self):
        job = self.store.save_image(self.job, b'jpeg-test', (200,200), 'product_metadata')
        link = 'https://track.example.com/?url=https%3A%2F%2Fshop.example.com%2Fp%2F1&token=new'
        current = self.store.enqueue({**self.row, 'shop_url_1':link, 'thumbnail':self.store.url(job)})
        self.assertEqual(current['object_key'], job['object_key'])
        self.assertEqual(current['expires_at'], job['expires_at'])
        self.assertEqual(current['payload']['shop_url_1'], link)
        self.assertEqual(current['payload']['fallback'], self.row['thumbnail'])
        self.assertEqual(self.store.due(), [])

    def test_publish_is_retried_without_downloading_image_again(self):
        job = self.store.save_image(self.job, b'jpeg-test', (200,200), 'product_metadata')
        deals = Mock()
        run(self.store, deals)
        deals.publish.assert_called_once_with(job, self.store.url(job))
        self.assertTrue(self.store.get(12)['published'])

    def test_low_disk_stops_writing_images(self):
        with patch('gadmin.thumbnails.store.shutil.disk_usage', return_value=Mock(free=1024)):
            with self.assertRaisesRegex(ThumbnailError, 'storage_low'):
                self.store.save_image(self.job, b'jpeg-test', (200,200), 'product_metadata')
        self.assertEqual(list(self.store.objects.iterdir()), [])

    def test_expiry_clears_db_reference_before_file_and_does_not_extend_on_access(self):
        job = self.store.save_image(self.job, b'jpeg-test', (200, 200), 'product_metadata')
        path = self.store.path(job['object_key'])
        self.clock += TTL_SECONDS - 1
        self.store.enqueue({**self.row, 'thumbnail':self.store.url(job)})
        clear = Mock(side_effect=lambda *args:self.assertTrue(path.exists()))
        self.assertEqual(self.store.expire(clear), 0)
        self.clock += 1
        self.assertEqual(self.store.expire(clear), 1)
        clear.assert_called_once_with(job, self.store.url(job))
        self.assertFalse(path.exists())
        self.assertEqual(self.store.get(12)['status'], 'expired')

    def test_database_error_preserves_file_for_expiry_retry(self):
        job = self.store.save_image(self.job, b'jpeg-test', (200, 200), 'product_metadata')
        self.clock += TTL_SECONDS
        with self.assertRaises(RuntimeError):
            self.store.expire(Mock(side_effect=RuntimeError('db unavailable')))
        self.assertTrue(self.store.path(job['object_key']).is_file())

    def test_invalid_paths_cannot_escape_storage(self):
        for key in ('../secret', '/etc/passwd', '20260101/../../secret'):
            with self.assertRaises(ValueError):
                self.store.path(key)


if __name__ == '__main__':
    unittest.main()
