from unittest.mock import patch
from django.test import TestCase
from django.utils import timezone
from gadmin.deals.models import Deal, DealClassification, DealMeasurements, ClassificationState
from gadmin.deals.serializer import DealSerializer
from gadmin.metrics.jobs import process_batch, backfill, snapshot
from gadmin.metrics.parser import analyze
from gadmin.categories.worker import enqueue_rule_upgrade


class JobsTests(TestCase):
    def deal(self, **values):
        return Deal.objects.create(subject='생수 500ml 24개 (12,000원/무료)',price=12000,currency='WON',write_at=timezone.now(),crawled_at=timezone.now(),**values)

    def test_manual_category_does_not_stop_numeric_processing(self):
        deal=self.deal()
        DealClassification.objects.create(deal=deal,input_title=deal.subject,category='food',source='manual',manual_override=True,status='ready')
        job=DealMeasurements.objects.create(deal=deal,input=snapshot(deal))
        process_batch()
        job.refresh_from_db()
        self.assertEqual(job.status,'ready')
        self.assertEqual(job.result['volume_ml']['total'],'12000')
        self.assertEqual(deal.classification.category,'food')
        self.assertTrue(deal.classification.manual_override)

    def test_changed_input_rejects_old_measurement_result(self):
        deal=self.deal()
        job=DealMeasurements.objects.create(deal=deal,input=snapshot(deal))
        def concurrent_change(value):
            DealMeasurements.objects.filter(pk=job.pk).update(request_revision=2,input={**value,'price':15000},lease_until=None)
            return analyze(value)
        with patch('gadmin.metrics.jobs.analyze',side_effect=concurrent_change):
            process_batch(limit=1)
        job.refresh_from_db()
        self.assertEqual(job.request_revision,2)
        self.assertEqual(job.result,{})
        self.assertEqual(job.status,'pending')

    def test_new_jobs_precede_history_and_seed_is_idempotent(self):
        old,new=self.deal(),self.deal()
        first=DealMeasurements.objects.create(deal=old,input=snapshot(old),priority=10)
        second=DealMeasurements.objects.create(deal=new,input=snapshot(new))
        process_batch(limit=1)
        first.refresh_from_db(); second.refresh_from_db()
        self.assertEqual(first.status,'pending')
        self.assertEqual(second.status,'ready')
        backfill(); backfill()
        self.assertEqual(DealMeasurements.objects.count(),2)

    def test_api_hides_pending_and_returns_exact_evidence_without_n_plus_one(self):
        deal=self.deal()
        job=DealMeasurements.objects.create(deal=deal,input=snapshot(deal))
        self.assertIsNone(DealSerializer(Deal.objects.select_related('measurements','classification').get(pk=deal.pk)).data['measurements'])
        process_batch()
        with self.assertNumQueries(1):
            from gadmin.deals.views import DealViewSet
            data=DealSerializer(DealViewSet.queryset.all(),many=True).data
        self.assertEqual(data[0]['measurements']['unit_prices'][0]['amount_krw'],'100')
        self.assertEqual(data[0]['measurement_status'],'ready')

    def test_rule_upgrade_preserves_manual_decisions(self):
        manual,automatic=self.deal(),self.deal()
        DealClassification.objects.create(deal=manual,input_title=manual.subject,category='home',status='ready',source='manual',manual_override=True,classifier_version='2026-09-17-v1/rules-1')
        job=DealClassification.objects.create(deal=automatic,input_title=automatic.subject,status='review',classifier_version='2026-09-17-v1/rules-1')
        enqueue_rule_upgrade()
        job.refresh_from_db()
        self.assertEqual(job.status,'pending')
        self.assertEqual(job.request_revision,2)
        self.assertEqual(manual.classification.category,'home')
        self.assertTrue(manual.classification.manual_override)
