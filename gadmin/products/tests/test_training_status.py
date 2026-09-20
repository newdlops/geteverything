from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from gadmin.deals.models import ClassificationState
from gadmin.products.training_status import summary


class StatusSummaryTests(SimpleTestCase):
    def test_progress_is_for_current_stage_and_never_implies_promotion(self):
        data=summary({'status':'training','step':12,'total_steps':92,'at':1000},now=1100)
        self.assertEqual((data['current'],data['total']),(12,92))
        self.assertFalse(data['stale'])
        self.assertFalse(data['promoted'])
        self.assertFalse(summary({'status':'validated','promoted':True})['promoted'])
        self.assertTrue(summary({'status':'promoted','promoted':True})['promoted'])

    def test_resource_pause_and_stale_observation_are_visible(self):
        data=summary({'status':'caching_frozen_layers','resource_action':'pause','cached':21,'total_cache':56,'at':1000},now=1700)
        self.assertEqual(data['label'],'자원 여유 대기 중')
        self.assertEqual(data['current'],21)
        self.assertTrue(data['stale'])
        self.assertFalse(summary({'status':'promoted','at':1000},now=1700)['stale'])

    def test_missing_records_and_counts_do_not_imply_zero_training_examples(self):
        self.assertEqual(summary(None)['label'],'학습 기록 없음')
        self.assertFalse(summary({'status':'failed'})['has_examples'])
        self.assertEqual(summary({'status':'training','step':20,'total_steps':10})['current'],10)


class TrainingAdminTests(TestCase):
    def setUp(self):
        self.url=reverse('admin:deals_product_changelist')
        self.user=get_user_model().objects.create_user(username='training-review',is_staff=True,is_superuser=True)

    def test_only_authorized_admin_can_read_training_details_and_refresh_keeps_search(self):
        ClassificationState.objects.create(key='products:llm_training',value={
            'status':'caching_frozen_layers','cached':21,'total_cache':56,
            'training_examples':46,'validation_examples':10,'promoted':False})
        self.assertEqual(self.client.get(self.url).status_code,302)
        self.client.force_login(self.user)
        response=self.client.get(self.url,{'q':'cola'})
        self.assertContains(response,'전처리 21/56건')
        self.assertContains(response,'운영 반영 전')
        self.assertContains(response,self.url+'?q=cola')
        self.assertNotContains(response,'상품 식별에 사용 중')
        self.user.is_superuser=False;self.user.save()
        self.assertEqual(self.client.get(self.url).status_code,403)

    def test_rejected_candidate_shows_comparison_and_failed_checks(self):
        ClassificationState.objects.create(key='products:llm_training',value={
            'status':'rejected','validation_count':10,'baseline':{'correct':5},'candidate':{'correct':4},
            'gate':{'passed':False,'checks':{'generation_improved':False,'no_regressions':False}}})
        self.client.force_login(self.user)
        response=self.client.get(self.url)
        for text in ('검증 미통과','기존 5/10건','학습 후 4/10건','상품 식별 개선, 기존 정답 유지','기존 운영 모델을 유지합니다.'):
            self.assertContains(response,text)
