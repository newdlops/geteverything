from django.test import TestCase
from django.utils import timezone

from gadmin.deals.models import Deal, DealClassification
from gadmin.categories.upgrade import process_batch
from gadmin.categories.worker import RULE_VERSION, finish, enqueue_rule_upgrade


class UpgradeTests(TestCase):
    def create(self,title,**values):
        deal = Deal.objects.create(subject=title,write_at=timezone.now(),crawled_at=timezone.now())
        fields = {'input_title':title,'status':'review','priority':10,'classifier_version':'2026-09-17-v1/rules-2'}
        fields.update(values)
        return DealClassification.objects.create(deal=deal,**fields)

    def test_upgrade_preserves_manual_and_fresh_jobs_and_invalidates_old_work(self):
        old = self.create('물티슈 80매 20팩',source='llm',candidate='baby',classifier_version='old-model')
        manual = self.create('물티슈',category='baby',status='ready',manual_override=True)
        new = self.create('구운란',status='pending',priority=0)
        before = old.deal.update_at
        self.assertEqual(process_batch()[0],1)
        self.assertEqual(finish(old,category='baby'),0)
        old.refresh_from_db(); manual.refresh_from_db(); new.refresh_from_db(); old.deal.refresh_from_db()
        self.assertEqual((old.category,old.status,old.classifier_version),('home.hygiene','ready',RULE_VERSION))
        self.assertEqual(old.candidate,'')
        self.assertEqual(old.deal.update_at,before)
        self.assertEqual(manual.category,'baby')
        self.assertEqual(new.status,'pending')
        self.assertEqual(process_batch()[0],0)

    def test_batches_are_bounded_and_ambiguous_history_stays_review(self):
        first = self.create('설명 없는 신제품')
        second = self.create('참기름 350ml')
        count,cursor = process_batch(1)
        self.assertEqual((count,cursor),(1,second.pk))
        self.assertEqual(process_batch(1,cursor)[0],1)
        first.refresh_from_db()
        self.assertEqual(first.status,'review')
        self.assertEqual(first.classifier_version,RULE_VERSION)

    def test_background_upgrade_includes_old_model_suggestions(self):
        job = self.create('감귤 3kg',source='llm',classifier_version='old-model')
        enqueue_rule_upgrade()
        job.refresh_from_db()
        self.assertEqual(job.status,'pending')
        self.assertEqual(job.priority,10)

    def test_new_taxonomy_reprocesses_previous_rules_and_reads_source_context(self):
        job=self.create('새로운 게임 제목')
        job.deal.community_name='ARCA'; job.deal.category='SW/게임'; job.deal.save()
        enqueue_rule_upgrade()
        job.refresh_from_db()
        self.assertEqual(job.status,'pending')
        self.assertEqual(process_batch()[0],1)
        job.refresh_from_db()
        self.assertEqual((job.category,job.classifier_version),('games',RULE_VERSION))
