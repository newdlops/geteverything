from datetime import timedelta
from unittest.mock import Mock, patch

from django.db import transaction
from django.test import TestCase
from django.utils import timezone

from gadmin.deals.models import ClassificationState, Deal, DealProduct, Product, ProductPrice
from gadmin.products import backfill, identity, jobs


class IdentityBackfillTests(TestCase):
    def job(self,title,**fields):
        deal=Deal.objects.create(subject=title,price=12000,currency='WON',community_name='TEST',
                                 write_at=timezone.now(),crawled_at=timezone.now())
        with transaction.atomic():row=jobs.seed(deal,historical=True)
        DealProduct.objects.filter(pk=row.pk).update(status='pending',last_error='awaiting_model_capacity',
            processor_version='products-3/product-extract-2',input_hash=identity.cache_hash(title),**fields)
        row.refresh_from_db()
        return row

    def known(self):
        row=self.job('매일두유 검은콩 190ml 24팩')
        model=Mock();model.structured.return_value={'is_product':True,'brand':'매일','name':'매일두유',
            'model':'','variant':'검은콩','category':'food'}
        jobs.process_llm(row,model)
        row.refresh_from_db()
        return row

    def test_old_capacity_waits_get_new_rules_without_changing_raw_prices(self):
        row=self.job('32GX870A 모니터')
        before=list(ProductPrice.objects.values('id','input','result','published_at','observed_at'))
        self.assertEqual(backfill.enqueue(),1)
        row.refresh_from_db()
        self.assertEqual((row.status,row.last_error,row.request_revision),('pending','backfill_rule_upgrade',2))
        self.assertEqual(jobs.process_rules(),1)
        row.refresh_from_db()
        self.assertEqual((row.status,row.product.model),('ready','32gx870a'))
        self.assertEqual(before,list(ProductPrice.objects.values('id','input','result','published_at','observed_at')))
        self.assertEqual(backfill.enqueue(),0)
        self.assertEqual(backfill.refresh_status()['linked_since_start'],1)

    def test_manual_connections_and_completed_identities_are_not_requeued(self):
        manual=self.job('수동 검토를 유지하는 상품',manual_override=True)
        connected=self.job('AMD 9800X3D');jobs.process_rule(connected)
        before=DealProduct.objects.get(pk=connected.pk).request_revision
        self.assertEqual(backfill.enqueue(),0)
        self.assertEqual(DealProduct.objects.get(pk=manual.pk).request_revision,1)
        self.assertEqual(DealProduct.objects.get(pk=connected.pk).request_revision,before)

    def test_live_lease_is_deferred_then_resumed_and_old_results_cannot_overwrite(self):
        stale=self.job('AMD 9800X3D',lease_until=timezone.now()+timedelta(minutes=2))
        self.assertEqual(backfill.enqueue(),0)
        self.assertEqual(backfill.refresh_status()['phase'],'rules')
        DealProduct.objects.filter(pk=stale.pk).update(lease_until=timezone.now()-timedelta(seconds=1))
        self.assertEqual(backfill.enqueue(),1)
        self.assertEqual(jobs.resolve(stale,identity.extract_rule(stale.input_title),'llm'),0)
        self.assertEqual(jobs.process_rules(),1)
        self.assertEqual(backfill.refresh_status()['phase'],'complete')

    def test_queue_is_bounded_and_resumes_without_requeuing_the_same_revision(self):
        rows=[self.job('AMD 9800X3D') for _ in range(5)]
        with patch.object(backfill,'RULE_QUEUE_LIMIT',2):
            self.assertEqual(backfill.enqueue(),2)
            self.assertEqual(backfill.enqueue(),0)
            self.assertEqual(jobs.process_rules(),2)
            self.assertEqual(backfill.enqueue(),2)
            self.assertEqual(jobs.process_rules(),2)
            self.assertEqual(backfill.enqueue(),1)
            self.assertEqual(jobs.process_rules(),1)
        self.assertEqual(Product.objects.filter(is_active=True).count(),1)
        self.assertEqual(ProductPrice.objects.count(),5)
        self.assertEqual(set(DealProduct.objects.values_list('request_revision',flat=True)),{2})
        self.assertEqual(backfill.refresh_status()['queued'],5)

    def test_unresolved_titles_remain_in_model_phase_after_rule_pass(self):
        self.job('로지텍 MX Master 4 무선 마우스')
        backfill.enqueue();jobs.process_rules()
        state=backfill.refresh_status()
        self.assertEqual((state['phase'],state['stale_remaining'],state['model_queued']),('model',0,1))
        self.assertIn('rules_completed_at',state)

    def test_cache_fills_waiting_posts_without_using_a_model_slot_or_relabelling_old_prices(self):
        row=self.job('매일두유 검은콩 190ml 48팩')
        with patch.object(jobs,'MODEL_QUEUE_LIMIT',0):jobs.process_rule(row)
        known=self.known()
        old=ProductPrice.objects.create(deal_id=row.pk,identity_revision=0,price_revision=0,
            published_at=timezone.now()-timedelta(days=1),input={'subject':'이전에 팔던 다른 상품','price':9000})
        self.assertEqual(backfill.reuse_cached(),1)
        row.refresh_from_db()
        self.assertEqual((row.status,row.product_id),('ready',known.product_id))
        self.assertIsNone(ProductPrice.objects.get(pk=old.pk).product_id)
        self.assertEqual(ProductPrice.objects.filter(deal_id=row.pk,identity_revision=1).get().product_id,known.product_id)
        self.assertEqual(backfill.reuse_cached(),0)

    def test_cache_never_fills_different_specs_manual_rows_or_active_model_leases(self):
        self.known()
        size=self.job('매일두유 검은콩 190ml 48캔')
        self.assertEqual(size.input_hash,identity.cache_hash('매일두유 검은콩 190ml 24팩'))
        manual=self.job('매일두유 검은콩 190ml 48팩',manual_override=True)
        leased=self.job('매일두유 검은콩 190ml 48팩',lease_until=timezone.now()+timedelta(minutes=3))
        for row in (size,manual,leased):
            DealProduct.objects.filter(pk=row.pk).update(processor_version=jobs.VERSION,
                extraction={'attributes':identity.facts(row.input_title)})
        self.assertEqual(backfill.reuse_cached(),0)
        self.assertEqual(DealProduct.objects.filter(pk__in=[size.pk,manual.pk,leased.pk],product=None).count(),3)

    def test_conflicting_cached_products_are_not_selected_arbitrarily(self):
        known=self.known()
        other=self.job(known.input_title)
        product=Product.objects.create(identity_key='different',name='다르게 추출된 상품',attributes=known.product.attributes)
        DealProduct.objects.filter(pk=other.pk).update(status='ready',product=product,processor_version=jobs.VERSION,extraction=known.extraction)
        waiting=self.job('매일두유 검은콩 190ml 48팩')
        DealProduct.objects.filter(pk=waiting.pk).update(processor_version=jobs.VERSION,
            extraction={'attributes':identity.facts(waiting.input_title)})
        self.assertIsNone(jobs.cached_product(waiting.input_title))
        self.assertEqual(backfill.reuse_cached(),0)
