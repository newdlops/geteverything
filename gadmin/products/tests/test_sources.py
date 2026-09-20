import base64
from datetime import timedelta
from unittest.mock import Mock
from urllib.parse import quote

from django.db import transaction
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from gadmin.deals.models import ClassificationState, Deal, DealProduct, ProductPrice, ProductReference, ProductSource
from gadmin.products import identifiers, identity, jobs, sources
from gadmin.thumbnails.fetch import Download, ThumbnailError


class IdentifierTests(SimpleTestCase):
    def test_real_multi_option_titles_cannot_be_used_as_single_product_evidence(self):
        for title in [
            '네네치킨 네꼬닭 저당소스 닭다리 25팩, 기본소스 순살닭다리 25팩, 소스닭가슴살 30팩 등',
            '네네치킨 네꼬닭 저당소스 순살 닭다리살 35팩 (+오트밀스테이크 1팩 증정) 및 기타 옵션',
            '단백질음료 테이크핏 250ml 9+9개 맛선택(총18개)',
            '사세 버팔로윙봉 820g 1+1 가리아게 치킨너겟 (19,904원/무료)',
            '이너홈 알카라인 건전지 AA, AAA 40개',
            '한돈 고추장양념 오돌뼈 250g 매움 더매움 990원',
        ]:
            with self.subTest(title=title):
                self.assertEqual(identity.offer_issue(title), 'not_a_single_product')
        for title in ['코카콜라 190ml 24캔', '맥반석 구운란 30구+30구',
                      '도브 바디워시 1L 2개 + 샤워볼 증정', '사세 버팔로윙봉 820g 1+1',
                      '닭다리 25팩 + 닭가슴살 1팩 증정']:
            self.assertEqual(identity.offer_issue(title), '', title)

    def test_bluetooth_is_not_a_blue_color_option(self):
        self.assertNotIn('blue', identity.facts('로지텍 MX Master 4 블루투스 마우스')['options'])
        self.assertIn('blue', identity.facts('로지텍 블루 마우스')['options'])

    def test_wrappers_mobile_and_tracking_parameters_share_a_key(self):
        target = 'https://m.brand.naver.com/dongwon/products/5808906085?NaPm=tracking'
        encoded = base64.b64encode(target.encode()).decode()
        links = [target, 'https://smartstore.naver.com/dongwon/products/5808906085',
            'https://unsafelink.com/' + target,
            'https://link.fmkorea.org/link.php?url=' + quote(quote(target, safe=''), safe=''),
            'https://s.ppomppu.co.kr/?target=' + quote(encoded) + '&encode=1',
            'https://click.linkprice.com/click.php?tu=' + quote(target, safe='')]
        keys = [identifiers.extract(url)[0]['key'] for url in links]
        self.assertEqual(len(set(keys)), 1)
        self.assertNotIn('NaPm', identifiers.extract(target)[0]['canonical_url'])

    def test_merchant_store_and_option_ids_have_separate_namespaces(self):
        a = identifiers.extract('https://smartstore.naver.com/store1/products/123')[0]
        b = identifiers.extract('https://smartstore.naver.com/store2/products/123')[0]
        c = identifiers.extract('https://item.gmarket.co.kr/Item?goodscode=123')[0]
        self.assertEqual(len({a['key'], b['key'], c['key']}), 3)
        rows = identifiers.extract('https://www.coupang.com/vp/products/123?itemId=456&vendorItemId=789&channel=foo')
        self.assertEqual({row['namespace'] for row in rows}, {'coupang.product', 'coupang.item', 'coupang.vendor_item'})
        self.assertEqual([row['value'] for row in identifiers.preferred(rows)], ['789'])

    def test_supported_detail_routes(self):
        for url, namespace, value in [
            ('https://itempage3.auction.co.kr/DetailView.aspx?ItemNo=e1234', 'auction', 'E1234'),
            ('https://www.11st.co.kr/products/1234?x=1', '11st', '1234'),
            ('https://www.lotteon.com/p/product/LO2476192302', 'lotteon', 'LO2476192302'),
            ('https://store.kakao.com/official/products/1234', 'kakao', '1234'),
            ('https://store.ohou.se/goods/1234', 'ohou.goods', '1234'),
            ('https://ko.aliexpress.com/item/100500123456.html', 'aliexpress', '100500123456'),
            ('https://www.amazon.com/description/dp/B012345678/ref=x', 'amazon', 'B012345678'),
            ('https://www.ssg.com/item/itemView.ssg?itemId=1234', 'ssg', '1234'),
            ('https://www.musinsa.com/products/1234', 'musinsa', '1234'),
            ('https://shop.example.com/product/detail.html?product_no=1234', 'storefront', '1234'),
        ]:
            with self.subTest(url=url):
                row = identifiers.extract(url)[0]
                self.assertEqual((row['namespace'], row['value']), (namespace, value))

    def test_listing_pages_lookalike_hosts_credentials_and_ambiguous_parameters_are_rejected(self):
        for url in ['https://www.coupang.com.evil.test/vp/products/123',
                    'https://www.coupang.com@evil.test/vp/products/123',
                    'https://brand.naver.com/store/best', 'https://item.gmarket.co.kr/search?goodscode=123',
                    'https://item.gmarket.co.kr/Item?goodscode=123&goodsCode=456',
                    'https://www.coupang.com:9999/vp/products/123', 'javascript:alert(1)']:
            self.assertEqual(identifiers.extract(url), [], url)

    def test_optional_sku_is_preserved_and_arbitrary_sites_are_not_fetched(self):
        rows = identifiers.extract('https://ko.aliexpress.com/item/100500123.html?sku_id=456')
        self.assertEqual(identifiers.preferred(rows)[0]['value'], '100500123:456')
        self.assertTrue(identifiers.needs_redirect('https://naver.me/abcd'))
        self.assertFalse(identifiers.needs_redirect('http://127.0.0.1/path'))
        self.assertFalse(identifiers.needs_redirect('https://unknown.example/123'))


class SourceWorkflowTests(TestCase):
    url = 'https://smartstore.naver.com/logitech/products/123456'
    title = '로지텍 MX Master 4 무선 마우스'
    extraction = {'is_product': True, 'brand': '로지텍', 'name': 'MX Master 4',
                  'model': 'MX Master 4', 'variant': '', 'category': 'computer'}

    def deal(self, title=None, url=None, price=12000):
        deal = Deal.objects.create(subject=title or self.title, shop_url_1=url or self.url,
            price=price, currency='WON', community_name='TEST', crawled_at=timezone.now(), write_at=timezone.now())
        with transaction.atomic():
            jobs.seed(deal, historical=True)
        sources.collect_pending()
        return deal

    def anchor(self, title=None, url=None, data=None):
        deal = self.deal(title, url)
        job = DealProduct.objects.get(pk=deal.pk)
        extracted = data or identity.grounded(deal.subject, self.extraction)[0]
        jobs.resolve(job, extracted, 'llm')
        return DealProduct.objects.get(pk=deal.pk)

    def test_same_id_reuses_a_product_for_a_different_title_without_model_work(self):
        anchor = self.anchor()
        deal = self.deal('로지텍 MX Master 4 블루투스 마우스 2개 (22,000원/무료)', price=22000)
        job = DealProduct.objects.get(pk=deal.pk)
        self.assertEqual((job.source, job.status, job.product_id), ('identifier', 'ready', anchor.product_id))
        self.assertEqual(job.extraction['shop_evidence']['value'], '123456')
        self.assertEqual(ProductPrice.objects.count(), 2)
        self.assertEqual(ProductPrice.objects.get(deal=deal).input['price'], 22000)

    def test_same_product_can_have_identifiers_from_multiple_merchants(self):
        first = self.deal('코카콜라 190ml 24캔')
        second = self.deal('코카콜라 190ml 48캔', 'https://item.gmarket.co.kr/Item?goodscode=999')
        for deal in (first, second):
            jobs.process_rule(DealProduct.objects.get(pk=deal.pk))
        links = DealProduct.objects.filter(pk__in=[first.pk, second.pk])
        self.assertEqual(links.values('product_id').distinct().count(), 1)
        self.assertEqual(set(ProductReference.objects.values_list('namespace', flat=True)), {'naver', 'gmarket'})

    def test_attached_set_label_keeps_the_same_weight_for_a_real_listing_pair(self):
        title = '신세계푸드 호주산 LA갈비 3kg 선물세트 (83,840원/무료)'
        data = identity.grounded(title, {'is_product': True, 'brand': '신세계푸드', 'name': '호주산 LA갈비',
                                        'model': '', 'variant': '', 'category': 'food'})[0]
        anchor = self.anchor(title, data=data)
        newer = self.deal('신세계푸드 선물세트 호주산 LA갈비 양념 3kg세트 (카드 82,940원/무료)')
        self.assertEqual(identity.facts(newer.subject)['sizes'], ['weight_g:3E+3'])
        self.assertEqual(DealProduct.objects.get(pk=newer.pk).product_id, anchor.product_id)

    def test_title_conflicts_override_a_shared_listing_id(self):
        self.anchor()
        for title in ['로지텍 MX Master 3S 무선 마우스', '로지텍 MX Master 4 케이스',
                      '로지텍 MX Master 4 외 3종 중 선택']:
            deal = self.deal(title)
            self.assertIsNone(sources.match(DealProduct.objects.get(pk=deal.pk)), title)
        for a, b in [('코카콜라 제로 355ml 24캔', '코카콜라 제로 500ml 24캔'),
                     ('코카콜라 제로 355ml 24캔', '코카콜라 제로 라임 355ml 24캔'),
                     ('삼성 990 PRO 1TB', '삼성 990 PRO 2TB')]:
            self.anchor(a, data=identity.extract_rule(a))
            deal = self.deal(b)
            self.assertIsNone(sources.match(DealProduct.objects.get(pk=deal.pk)), b)

    def test_store_collision_and_different_explicit_options_do_not_use_parent_id(self):
        self.anchor()
        deal = self.deal(url=self.url.replace('/logitech/', '/another-store/'))
        self.assertIsNone(sources.match(DealProduct.objects.get(pk=deal.pk)))
        self.anchor(url='https://www.coupang.com/vp/products/123?itemId=11&vendorItemId=111')
        deal = self.deal(url='https://www.coupang.com/vp/products/123?itemId=22&vendorItemId=222')
        self.assertIsNone(sources.match(DealProduct.objects.get(pk=deal.pk)))

    def test_shared_listing_does_not_merge_aa_and_aaa_battery_sizes(self):
        title = '이너홈 알카라인 AA 건전지 40개'
        data = identity.grounded(title, {'is_product': True, 'brand': '이너홈', 'name': '알카라인',
                                        'model': '', 'variant': '', 'category': 'electronics'})[0]
        self.anchor(title, data=data)
        different = self.deal('이너홈 알카라인 AAA 건전지 40개')
        self.assertIsNone(DealProduct.objects.get(pk=different.pk).product_id)

    def test_two_products_claiming_the_same_id_are_not_arbitrarily_chosen(self):
        first = self.anchor()
        second_deal = self.deal()
        from gadmin.deals.models import Product
        duplicate = Product.objects.create(identity_key='different', name='별도 검토 상품', attributes=first.product.attributes)
        DealProduct.objects.filter(pk=second_deal.pk).update(product=duplicate, extraction=first.extraction, status='ready')
        new_deal = self.deal('로지텍 MX Master 4 블루투스 마우스')
        self.assertIsNone(sources.match(DealProduct.objects.get(pk=new_deal.pk)))

    def test_stale_collection_cannot_restore_replaced_links(self):
        deal = self.deal()
        old = ProductSource.objects.get(pk=deal.pk)
        updated = {**old.input, 'urls': ['https://item.gmarket.co.kr/Item?goodscode=999', '']}
        ProductSource.objects.filter(pk=deal.pk).update(input=updated, revision=old.revision + 1, status='pending')
        self.assertFalse(sources.persist(old, sources.references(old.input)))
        sources.collect_pending()
        self.assertEqual(list(ProductReference.objects.filter(source_id=deal.pk).values_list('value', flat=True)), ['999'])

    def test_manual_assignment_and_previous_title_price_generation_are_preserved(self):
        anchor = self.anchor()
        deal = self.deal('로지텍 MX Master 4 블루투스 마우스')
        job = DealProduct.objects.get(pk=deal.pk)
        jobs.manual_assign(deal.pk, None, 'operator', job.request_revision)
        self.assertEqual(sources.try_link(deal.pk), 0)
        self.assertIsNone(DealProduct.objects.get(pk=deal.pk).product_id)
        other = self.deal('로지텍 MX Master 4 무선 마우스 세일')
        ProductPrice.objects.filter(deal=other).update(identity_revision=0, product=None)
        DealProduct.objects.filter(pk=other.pk).update(status='pending', product=None)
        self.assertEqual(sources.try_link(other.pk), 1)
        self.assertIsNone(ProductPrice.objects.get(deal=other).product_id)
        self.assertEqual(DealProduct.objects.get(pk=other.pk).product_id, anchor.product_id)

    def test_waiting_posts_are_revisited_when_an_anchor_becomes_available(self):
        waiting = self.deal('로지텍 MX Master 4 블루투스 마우스')
        anchor = self.anchor()
        self.assertEqual(sources.revisit_waiting(), 1)
        self.assertEqual(DealProduct.objects.get(pk=waiting.pk).product_id, anchor.product_id)

    def test_late_model_result_cannot_replace_an_identifier_link(self):
        waiting = self.deal('로지텍 MX Master 4 블루투스 마우스')
        stale = DealProduct.objects.get(pk=waiting.pk)
        anchor = self.anchor()
        self.assertEqual(sources.try_link(waiting.pk), 1)
        self.assertEqual(jobs.finish(stale, status='review', last_error='model_abstained'), 0)
        current = DealProduct.objects.get(pk=waiting.pk)
        self.assertEqual((current.status, current.product_id), ('ready', anchor.product_id))
        self.assertGreater(current.request_revision, stale.request_revision)

    def test_redirect_result_is_cached_and_has_bounded_retries(self):
        deal = self.deal(url='https://naver.me/abcd')
        self.assertLessEqual(ProductSource.objects.get(pk=deal.pk).next_attempt_at, timezone.now())
        ProductSource.objects.filter(pk=deal.pk).update(next_attempt_at=timezone.now())
        downloader = Mock(return_value=Download(self.url, b'', ''))
        sources.resolve_redirects_once(downloader)
        self.assertEqual(ProductSource.objects.get(pk=deal.pk).status, 'ready')
        self.assertEqual(ProductReference.objects.get(source_id=deal.pk).evidence, 'redirect')
        cached = ClassificationState.objects.get(key__startswith='products:redirect:')
        cached.full_clean()
        self.assertEqual(len(cached.key), 64)
        second = self.deal(url='https://naver.me/abcd')
        ProductSource.objects.filter(pk=second.pk).update(next_attempt_at=timezone.now())
        sources.resolve_redirects_once(downloader)
        self.assertEqual(downloader.call_count, 1)
        failed = self.deal(url='https://naver.me/blocked')
        downloader.side_effect = ThumbnailError('http_403')
        for _ in range(3):
            ProductSource.objects.filter(pk=failed.pk).update(next_attempt_at=timezone.now())
            sources.resolve_redirects_once(downloader)
        self.assertEqual((ProductSource.objects.get(pk=failed.pk).status, ProductSource.objects.get(pk=failed.pk).attempts), ('unresolved', 3))
        self.assertEqual(sources.resolve_redirects_once(downloader), 0)

    def test_collecting_again_does_not_add_prices_or_rewrite_manual_links(self):
        anchor = self.anchor()
        prices = list(ProductPrice.objects.values('id', 'input', 'identity_revision', 'price_revision'))
        ProductSource.objects.filter(pk=anchor.pk).update(status='pending')
        sources.collect_pending()
        self.assertEqual(list(ProductPrice.objects.values('id', 'input', 'identity_revision', 'price_revision')), prices)
        self.assertEqual(ProductReference.objects.filter(source_id=anchor.pk).count(), 1)
