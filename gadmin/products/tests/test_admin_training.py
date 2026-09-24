from django.db import transaction
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from django.urls import reverse

from gadmin.deals.models import ClassificationState, Deal, DealProduct
from gadmin.products import identity, jobs
from gadmin.products.admin import AssignmentForm


class ExtractionReviewFormTests(TestCase):
    title = '로지텍 MX Master 4 무선 마우스'

    def setUp(self):
        deal = Deal.objects.create(subject=self.title, community_name='TEST',
            write_at=timezone.now(), crawled_at=timezone.now())
        with transaction.atomic():
            jobs.seed(deal)
        self.job = DealProduct.objects.get(pk=deal.pk)
        data = identity.grounded(self.title, {
            'is_product': True, 'brand': '로지텍', 'name': 'MX Master 4',
            'model': 'MX Master 4', 'variant': '', 'category': 'computer'})[0]
        jobs.resolve(self.job, data, 'llm')
        self.job.refresh_from_db()
        user=get_user_model().objects.create_user(username='extraction-reviewer',password='test',
            is_staff=True,is_superuser=True)
        self.client.force_login(user)

    def form(self, **overrides):
        values = {
            'product': str(self.job.product_id),
            'revision': str(self.job.request_revision),
            'confirm_extraction': 'on',
            'training_brand': '로지텍',
            'training_name': 'MX Master 4',
            'training_model': 'MX Master 4',
            'training_variant': '',
            'training_category': 'computer',
        }
        values.update(overrides)
        return AssignmentForm(values, instance=self.job)

    def test_checked_title_grounded_extraction_becomes_explicit_training_target(self):
        form = self.form()
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['llm_target'], {
            'brand': '로지텍', 'name': 'MX Master 4', 'model': 'MX Master 4',
            'variant': '', 'is_product': True, 'category': 'computer'})

    def test_ungrounded_fields_and_missing_product_are_rejected(self):
        ungrounded = self.form(training_brand='애플')
        self.assertFalse(ungrounded.is_valid())
        self.assertIn('제목 근거', str(ungrounded.errors))
        missing_product = self.form(product='')
        self.assertFalse(missing_product.is_valid())
        self.assertIn('상품을 먼저 선택', str(missing_product.errors))

    def test_unchecked_extraction_is_not_added_to_training_targets(self):
        form = self.form(confirm_extraction='')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertNotIn('llm_target', form.cleaned_data)

    def test_single_product_abstention_requires_an_empty_link_and_explicit_confirmation(self):
        negative=self.form(product='',training_not_product='on')
        self.assertTrue(negative.is_valid(),negative.errors)
        self.assertEqual(negative.cleaned_data['llm_target'],{
            'brand':'','name':'','model':'','variant':'',
            'is_product':False,'category':'unknown'})
        self.assertFalse(self.form(training_not_product='on').is_valid())
        self.assertFalse(self.form(product='',confirm_extraction='',training_not_product='on').is_valid())

    def test_admin_page_exposes_grounded_training_fields_and_saves_checked_label(self):
        url=reverse('admin:deals_dealproduct_change',args=[self.job.pk])
        page=self.client.get(url)
        self.assertEqual(page.status_code,200)
        self.assertContains(page,'LLM 학습 정답 (선택)')
        self.assertContains(page,'confirm_extraction')
        response=self.client.post(url,{
            'product':str(self.job.product_id),'revision':str(self.job.request_revision),
            'confirm_extraction':'on','training_brand':'로지텍','training_name':'MX Master 4',
            'training_model':'MX Master 4','training_variant':'','training_category':'computer','_save':'저장'})
        self.assertEqual(response.status_code,302)
        from gadmin.deals.models import ProductMatchExample
        example=ProductMatchExample.objects.get(origin='operator',left_title=self.title)
        self.assertEqual(example.extraction['llm_target']['name'],'MX Master 4')

    def test_product_list_shows_daily_review_candidates_without_treating_them_as_labels(self):
        ClassificationState.objects.create(key='products:quality',value={
            'at':'2026-09-24T12:00:00+09:00','cross_post_conflict_products':1,
            'numeric_split_review_groups':1,'conflict_candidates':[{
                'product_id':str(self.job.product_id),'name':'MX Master 4',
                'linked_posts':2}], 'review_candidates':[]})
        page=self.client.get(reverse('admin:deals_product_changelist'))
        self.assertEqual(page.status_code,200)
        self.assertContains(page,'상품 연결 품질 점검')
        self.assertContains(page,'운영자 확인 추출 정답 0건')
        self.assertContains(page,reverse('admin:deals_product_history',args=[self.job.product_id]))

    def test_admin_can_review_a_mixed_listing_as_a_negative_lora_example(self):
        title='펩시 제로 310ml 24캔 / 코카콜라 355ml 24캔'
        deal=Deal.objects.create(subject=title,community_name='TEST',
            write_at=timezone.now(),crawled_at=timezone.now())
        with transaction.atomic():jobs.seed(deal)
        job=DealProduct.objects.get(pk=deal.pk)
        url=reverse('admin:deals_dealproduct_change',args=[job.pk])
        response=self.client.post(url,{
            'product':'','revision':str(job.request_revision),'confirm_extraction':'on',
            'training_not_product':'on','training_category':'unknown','_save':'저장'})
        self.assertEqual(response.status_code,302)
        job.refresh_from_db()
        self.assertIsNone(job.product_id)
        self.assertEqual(job.status,'review')
        from gadmin.deals.models import ProductMatchExample
        example=ProductMatchExample.objects.get(origin='operator',left_title=title,right_title='')
        self.assertFalse(example.extraction['llm_target']['is_product'])
