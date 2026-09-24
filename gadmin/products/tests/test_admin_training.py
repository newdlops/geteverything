from django.db import transaction
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from django.urls import reverse

from gadmin.deals.models import Deal, DealProduct
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
