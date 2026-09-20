import copy
import json
from unittest.mock import Mock, patch
from django.test import SimpleTestCase, TestCase
from django.db import transaction
from django.utils import timezone
from gadmin.deals.models import Deal, DealProduct, ProductMatchExample
from gadmin.products import identity, jobs, local_model, sft
from gadmin.products.sft_validation import promotion_gate, pair_scores


class TrainingDataTests(SimpleTestCase):
    def test_reviewed_bundle_examples_stay_in_one_split(self):
        rows=sft.bootstrap_rows()
        self.assertTrue(all(sft.valid_target(r['title'],r['target']) for r in rows))
        data=sft.dataset(rows)
        self.assertGreaterEqual(len(rows),300)
        self.assertGreaterEqual(len(data['validation']),40)
        self.assertGreaterEqual(sum(not r['target']['is_product'] for r in data['validation']),8)
        for key in ('family','title'):
            self.assertFalse({r[key] for r in data['train']} & {r[key] for r in data['validation']})
        aliases=lambda group:{identity.alias_title(r['title']) for r in group}
        self.assertFalse(aliases(data['train']) & aliases(data['validation']))
        previous_heldout={'nike','roborock','sony','iphone','vague','mixed-soda'}
        self.assertTrue(previous_heldout <= {r['family'] for r in data['validation']})
        self.assertFalse(previous_heldout & {r['family'] for r in data['train']})
        self.assertEqual(sft.dataset(list(reversed(rows)))['sha256'],data['sha256'])

    def test_model_guesses_and_conflicting_labels_cannot_be_training_truth(self):
        rows=sft.bootstrap_rows()
        guessed=copy.deepcopy(rows[0]);guessed.update(origin='llm',title='모델이 지어낸 상품')
        self.assertEqual(sft.dataset(rows+[guessed])['sha256'],sft.dataset(rows)['sha256'])
        conflict=copy.deepcopy(rows[0]);conflict['target']['category']='home'
        with self.assertRaises(ValueError):sft.dataset(rows+[conflict])

    def test_mixed_products_never_become_single_product_labels(self):
        title='드시모네 키즈 스텝1 3박스+키즈 스텝2 15일분+요거트 1개입'
        self.assertFalse(sft.valid_target(title,dict(brand='드시모네',name='키즈 스텝',model='',variant='',is_product=True,category='food')))
        self.assertIsNone(identity.extract_rule('삼성 990 PRO 1TB+로지텍 마우스'))
        self.assertIsNotNone(identity.extract_rule('삼성 990 PRO 1TB+무료배송'))

    def test_only_approved_adapter_selects_the_training_prompt(self):
        row=sft.bootstrap_rows()[4]
        model=Mock();model.structured.return_value=row['target']
        with patch.object(local_model,'active_adapter',return_value={'adapter_id':0,'sha256':'a'*64}):
            result,reason,_=local_model.extract(model,row['title'])
        self.assertEqual(reason,'')
        self.assertEqual(result['llm_adapter_sha256'],'a'*64)
        self.assertEqual(model.structured.call_args.args[0],sft.SYSTEM)
        self.assertEqual(model.structured.call_args.kwargs,{'adapter':0})

    def test_promotion_requires_unseen_generation_improvement_and_zero_regressions(self):
        pairs={'same_pairs':20,'different_pairs':60,'false_merges':0,'false_splits':0}
        result={'probe':False,'validation_count':40,'validation_families':16,'validation_negatives':8,
                'lora_b_squared_norm':.1,'loss_gate':True,'regressions':0,
                'baseline':{'correct':20,'p95_seconds':50,'pairs':pairs},
                'candidate':{'correct':32,'valid':40,'false_merge':0,'p95_seconds':50,'pairs':pairs}}
        self.assertTrue(promotion_gate(result)['passed'])
        for change in ({'probe':True},{'loss_gate':False},{'regressions':1},{'validation_count':2},
                       {'validation_families':3},{'validation_negatives':1}):
            self.assertFalse(promotion_gate(result|change)['passed'])
        for change in ({'correct':20},{'correct':25},{'valid':39},{'false_merge':1},{'p95_seconds':250},
                       {'pairs':pairs|{'false_merges':1}},{'pairs':pairs|{'false_splits':1}}):
            self.assertFalse(promotion_gate(result|{'candidate':result['candidate']|change})['passed'])

    def test_pair_evaluation_detects_lost_flavour_distinctions_and_bundle_splits(self):
        target=lambda variant:dict(brand='테스트',name='과일음료',model='',variant=variant,is_product=True,category='food')
        rows=[{'title':'테스트 과일음료 사과 200ml 24팩','expected':target('사과'),'actual':target(''),'valid':True},
              {'title':'테스트 과일음료 딸기 200ml 24팩','expected':target('딸기'),'actual':target(''),'valid':True},
              {'title':'테스트 과일음료 사과 200ml 48팩','expected':target('사과'),'actual':target('사과'),'valid':True}]
        result=pair_scores(rows)
        self.assertEqual(result,{'same_pairs':1,'different_pairs':2,'false_merges':1,'false_splits':1})

    def test_category_requests_explicitly_disable_product_lora(self):
        from gadmin.categories.llm import LocalModel
        model=LocalModel()
        model.opener=Mock()
        model.opener.open.return_value.__enter__=Mock(return_value=Mock(read=Mock(return_value=json.dumps(
            {'choices':[{'finish_reason':'stop','message':{'content':'{"category":"food"}'}}]}).encode())))
        model.opener.open.return_value.__exit__=Mock(return_value=False)
        self.assertEqual(model.classify('우유'),'food')
        request=model.opener.open.call_args.args[0]
        self.assertEqual(json.loads(request.data)['lora'],[])


class ReviewedFeedbackTests(TestCase):
    def test_manual_confirmation_exports_the_grounded_target(self):
        title='로지텍 MX Master 4 무선 마우스'
        deal=Deal.objects.create(subject=title,community_name='TEST',write_at=timezone.now(),crawled_at=timezone.now())
        with transaction.atomic():jobs.seed(deal)
        job=DealProduct.objects.get(pk=deal.pk)
        data=identity.grounded(title,dict(brand='로지텍',name='MX Master 4',model='MX Master 4',variant='',is_product=True,category='computer'))[0]
        jobs.resolve(job,data,'llm')
        job.refresh_from_db()
        self.assertEqual(ProductMatchExample.objects.count(),0)
        jobs.manual_assign(deal.pk,job.product,'reviewer',job.request_revision)
        example=ProductMatchExample.objects.get()
        self.assertEqual(example.origin,'operator')
        self.assertTrue(sft.valid_target(title,example.extraction['llm_target']))
