from datetime import timedelta
from unittest.mock import Mock
from django.test import TestCase, RequestFactory
from django.utils import timezone
from django.contrib import admin
from gadmin.deals.models import Deal, DealClassification
from gadmin.deals.admin import DealClassificationAdmin
from gadmin.deals.serializer import DealSerializer
from gadmin.categories.worker import claim, finish, process_rule, process_llm, enqueue_backfill
from gadmin.categories.llm import Unavailable, InvalidResult


class WorkflowTests(TestCase):
    def create(self, title='아이폰16 케이스', **fields):
        deal = Deal.objects.create(subject=title, category='원본 분류', write_at=timezone.now(), crawled_at=timezone.now())
        return DealClassification.objects.create(deal=deal, input_title=title, **fields)

    def test_new_jobs_have_priority_and_leases_recover(self):
        old = self.create(priority=10)
        live = self.create(priority=0)
        self.assertEqual(claim('pending').pk, live.pk)
        self.assertEqual(claim('pending').pk, old.pk)
        self.assertIsNone(claim('pending'))
        DealClassification.objects.filter(pk=live.pk).update(lease_until=timezone.now()-timedelta(seconds=1))
        self.assertEqual(claim('pending').pk, live.pk)

    def test_stale_revision_cannot_publish(self):
        job = self.create()
        DealClassification.objects.filter(pk=job.pk).update(request_revision=2, input_title='모니터')
        self.assertEqual(finish(job, category='mobile'), 0)

    def test_manual_edit_wins_over_inflight_result(self):
        job = self.create()
        obj = DealClassification.objects.get(pk=job.pk)
        obj.category = 'food'
        DealClassificationAdmin(DealClassification, admin.site).save_model(RequestFactory().post('/'), obj, None, True)
        self.assertEqual(finish(job, category='mobile'), 0)
        job.refresh_from_db()
        self.assertTrue(job.manual_override)
        self.assertEqual(job.category, 'food')

    def test_rules_preserve_original_category_and_timestamps(self):
        job = self.create()
        previous = job.deal.update_at
        process_rule(job)
        job.refresh_from_db()
        job.deal.refresh_from_db()
        self.assertEqual(job.category, 'mobile.accessory')
        self.assertEqual(job.deal.category, '원본 분류')
        self.assertEqual(job.deal.update_at, previous)
        data = DealSerializer(Deal.objects.select_related('classification').get(pk=job.pk)).data
        self.assertEqual(data['standard_category']['parent_code'], 'mobile')

    def test_llm_defaults_to_review_and_never_exposes_candidate(self):
        job = self.create(title='상품 모델명', status='llm')
        model = Mock()
        model.classify.return_value = 'computer'
        process_llm(job, model, 'test-version')
        job.refresh_from_db()
        self.assertEqual(job.candidate, 'computer')
        self.assertEqual(job.status, 'review')
        self.assertEqual(job.category, '')

    def test_unloaded_model_does_not_exhaust_title_retries(self):
        job = self.create(status='llm')
        model = Mock()
        model.classify.side_effect = Unavailable()
        process_llm(job, model, 'test-version')
        job.refresh_from_db()
        self.assertEqual(job.attempts, 0)
        self.assertEqual(job.status, 'llm')

    def test_bad_output_retry_limit(self):
        job = self.create(status='llm', attempts=2)
        model = Mock()
        model.classify.side_effect = InvalidResult('invalid_model_output')
        process_llm(job, model, 'test-version')
        job.refresh_from_db()
        self.assertEqual(job.status, 'error')

    def test_backfill_does_not_reset_existing_manual_classification(self):
        job = self.create(category='fashion', status='ready', manual_override=True)
        Deal.objects.create(subject='김치 1kg', write_at=timezone.now(), crawled_at=timezone.now())
        enqueue_backfill(100)
        job.refresh_from_db()
        self.assertTrue(job.manual_override)
        self.assertEqual(job.category, 'fashion')
        self.assertEqual(DealClassification.objects.count(), 2)

    def test_history_does_not_spend_model_cpu_before_quality_gate(self):
        job = self.create(title='새로운 상품 모델명', priority=10)
        process_rule(job)
        job.refresh_from_db()
        self.assertEqual(job.status, 'review')

    def test_api_root_filter_includes_children_and_rejects_unknown(self):
        from rest_framework.test import APIRequestFactory
        from gadmin.deals.views import DealViewSet
        self.create(category='food.drink', status='ready')
        self.create(category='computer.monitor', status='ready')
        view = DealViewSet.as_view({'get': 'list'})
        response = view(APIRequestFactory().get('/api/deals/', {'standard_category':'food'}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['standard_category']['code'], 'food.drink')
        self.assertEqual(view(APIRequestFactory().get('/api/deals/', {'standard_category':'invalid'})).status_code, 400)

    def test_serializing_category_list_does_not_query_each_row(self):
        self.create(category='food', status='ready')
        self.create(category='computer', status='ready')
        with self.assertNumQueries(1):
            from gadmin.deals.views import DealViewSet
            data = DealSerializer(DealViewSet.queryset.all(), many=True).data
            self.assertEqual(len(data), 2)

    def test_same_title_in_different_source_categories_cannot_share_cached_result(self):
        first = self.create(title='명확하지 않은 모델명')
        first.deal.community_name='ARCA'; first.deal.category='식품'; first.deal.save()
        process_rule(first)
        second = self.create(title='명확하지 않은 모델명')
        second.deal.community_name='ARCA'; second.deal.category='SW/게임'; second.deal.save()
        process_rule(second)
        first.refresh_from_db(); second.refresh_from_db()
        self.assertEqual((first.category,second.category),('food','games'))
        self.assertNotEqual(first.title_hash,second.title_hash)

    def test_stale_metadata_revision_cannot_publish(self):
        job=self.create(title='낯선 모델명')
        # PostgreSQL's metadata trigger performs this revision increment.
        DealClassification.objects.filter(pk=job.pk).update(request_revision=2)
        self.assertEqual(process_rule(job),0)
        self.assertEqual(DealClassification.objects.get(pk=job.pk).status,'pending')
