from datetime import timedelta
from unittest.mock import Mock

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import SimpleTestCase, TestCase, tag
from django.urls import reverse
from django.utils import timezone

from gadmin.categories.llm import Unavailable
from gadmin.deals.models import (ClassificationState,Deal,DealProduct,Product,
                                 ProductMatcherVersion,ProductMatchExample,ProductPrice)
from gadmin.products import bootstrap,identity,jobs,learning,local_model
from gadmin.products.history import history


class IdentityTests(SimpleTestCase):
    def test_container_without_a_pack_count_is_still_explicit(self):
        for label,kind in [('캔','can'),('페트','pet'),('PET병','pet'),('유리병','glass'),('병','bottle')]:
            data=identity.extract_rule('코카콜라 190ml '+label)
            self.assertIsNotNone(data,label)
            self.assertEqual(data['attributes'].get('container'),kind,label)
        self.assertNotIn('container',identity.facts('코카콜라 190ml'))

    def test_pack_count_changes_price_basis_without_changing_identity(self):
        a=identity.extract_rule('코카콜라 제로 355ml 24캔 (12,000원/무료)')
        b=identity.extract_rule('코카콜라 제로 355ml 48캔 (22,000원/무료)')
        self.assertEqual(identity.signature(a),identity.signature(b))

    def test_forum_reply_count_and_checkout_terms_do_not_split_a_sku(self):
        base='펩시 제로 라임 310ml 24캔'
        reply=base+' [13]'
        checkout=base+' (카드, 티멤 19,900원/무료)'
        self.assertEqual(identity.signature(identity.extract_rule(base)),
                         identity.signature(identity.extract_rule(reply)))
        self.assertEqual(identity.signature(identity.extract_rule(base)),
                         identity.signature(identity.extract_rule(checkout)))
        self.assertNotIn('13',identity.facts(reply)['numeric_options'])
        self.assertEqual(identity.clean_title('삼성 990 PRO [1TB]'),'삼성 990 pro 1tb')

    def test_store_name_cannot_become_a_product_brand(self):
        title='[G마켓] COLORFUL iGame 지포스 RTX 5080 16GB'
        for brand in ('G마켓','[G마켓]'):
            data,_=identity.grounded(title,{'is_product':True,'brand':brand,
                'name':'COLORFUL iGame 지포스','model':'','variant':''})
            self.assertIsNone(data)
        title='[11번가] 안심포장 무항생제 특란 계란 30구'
        data,_=identity.grounded(title,{'is_product':True,'brand':'11번가',
            'name':'안심포장 무항생제 특란 계란','model':'','variant':''})
        self.assertIsNone(data)
        self.assertEqual(identity.clean_title('에어팟 프로3 [삼카,현카]'),'에어팟 프로3')
        data,_=identity.grounded('에어팟 프로3 [삼카,현카]',{'is_product':True,
            'brand':'에어팟','name':'프로3 삼카,현카','model':'','variant':''})
        self.assertIsNone(data)

    def test_size_flavor_and_model_are_hard_boundaries(self):
        for a,b in [('코카콜라 제로 355ml 24캔','코카콜라 제로 500ml 24캔'),
                    ('코카콜라 제로 355ml 24캔','코카콜라 제로 라임 355ml 24캔'),
                    ('삼성 990 PRO 1TB','삼성 990 PRO 2TB'),('삼성 990 PRO 1TB','삼성 980 PRO 1TB')]:
            self.assertNotEqual(identity.signature(identity.extract_rule(a)),identity.signature(identity.extract_rule(b)))
        self.assertNotEqual(identity.facts('갤럭시 S24'),identity.facts('갤럭시 S25'))

    def test_unknown_subline_and_mixed_offers_do_not_collapse_to_brand(self):
        for title in ['햇반 솥반 버섯영양밥 210g 24개','코카콜라 355ml 24캔+펩시 355ml 24캔',
                      '코카콜라 제로 355ml/500ml 24캔',
                      '펩시제로슈거 라임향 355ml 48캔외 종류 다양 (24,480원/무료배송)']:
            self.assertIsNone(identity.extract_rule(title),title)

    def test_accessory_and_caffeine_free_variant_cannot_be_merged_into_main_product(self):
        self.assertIsNone(identity.extract_rule('삼성 990 PRO 1TB 호환 방열판'))
        self.assertNotEqual(identity.facts('삼성 갤럭시 S25'),identity.facts('삼성 갤럭시 S25 케이스'))
        self.assertNotEqual(identity.signature(identity.extract_rule('코카콜라 제로 350ml 24개')),
            identity.signature(identity.extract_rule('코카콜라 제로제로 350ml 24개')))

    def test_food_grams_are_not_a_monitor_model_and_monitor_codes_are_not_grams(self):
        self.assertIsNone(identity.extract_rule('닥터유 단백질바 35gx20개'))
        self.assertEqual(identity.facts('LG 32GX870B 모니터')['sizes'],[])
        self.assertIsNotNone(identity.extract_rule('LG 32GX870B 모니터'))
        from gadmin.metrics.parser import quantities
        self.assertIsNone(quantities('LG 32GX870B')['weight_g'])

    def test_local_model_requires_grounded_names_and_preserves_numeric_specs(self):
        title='로지텍 MX Master 4 무선 마우스'
        raw={'is_product':True,'brand':'로지텍','name':'MX Master 4','model':'MX Master 4','variant':'','category':'computer'}
        model=Mock();model.structured.return_value=raw
        data,reason,_=local_model.extract(model,title)
        self.assertEqual(data['model'],'MX Master 4');self.assertEqual(reason,'')
        model.structured.return_value={**raw,'brand':'애플'}
        self.assertEqual(local_model.extract(model,title)[1],'ungrounded_product_fields')

    def test_semantically_wrong_but_title_grounded_fields_are_rejected(self):
        for title,raw in [
            ('광동 비타500 에이스 100ml 20병 네멤무배',{'brand':'네멤무','name':'비타500','model':'에이스','variant':'100ml 20병'}),
            ('매일두유 검은콩 190ml 48팩',{'brand':'두유','name':'검은콩','model':'190ml','variant':'48팩'}),
            ('매일두유 검은콩 190ml 48팩',{'brand':'매일','name':'매일두유','model':'190ml','variant':''}),
            ('법성포 참굴비 명선세트 6호 20미',{'brand':'법성포','name':'참굴비 명선세트','model':'','variant':''}),
        ]:
            self.assertIsNone(identity.grounded(title,{**raw,'is_product':True})[0])

    def test_pepsi_cola_brand_spelling_is_grounded_as_the_pepsi_brand(self):
        title='펩시콜라제로슈거 라임 310ml 24캔'
        raw={'is_product':True,'brand':'펩시콜라','name':'제로슈거 라임','model':'','variant':'',
             'category':'food'}
        data,reason=identity.grounded(title,raw)
        self.assertEqual(reason,'')
        self.assertEqual(identity.signature(data),identity.signature({**raw,'brand':'펩시','attributes':identity.facts(title)}))

    def test_selection_posts_and_bracketed_capacity_are_handled_before_linking(self):
        self.assertIsNone(identity.grounded('반스 올드스쿨 VN000D7ZFRN1 외 10종',{
            'is_product':True,'brand':'반스','name':'올드스쿨','model':'VN000D7ZFRN1','variant':''})[0])
        self.assertNotEqual(identity.facts('[1TB] 삼성 990 PRO'),identity.facts('[2TB] 삼성 990 PRO'))
        self.assertEqual(identity.facts('삼성 990 PRO (1TB/무료)')['specs'],['1tb'])
        self.assertEqual(identity.cache_hash('[쿠팡] 매일두유 190ml 24팩 (12,000원/무료)'),
                         identity.cache_hash('[네이버] 매일두유 190ml 48팩 (22,000원/무료)'))

    def test_matcher_is_actually_trained_and_holdout_does_not_share_targets(self):
        examples=list(bootstrap.examples())
        weights,metrics=learning.train(examples)
        self.assertTrue(any(abs(w)>.1 for w in weights))
        self.assertGreater(metrics['validation_count'],0)
        self.assertGreater(learning.probability(weights,learning.features('삼성 990 PRO 1TB','삼성 990 PRO 1TB')),
            learning.probability(weights,learning.features('삼성 990 PRO 2TB','삼성 990 PRO 1TB')))
        self.assertFalse(metrics['auto_match_enabled'])
        self.assertEqual(metrics['training_count']+metrics['validation_count'],len(examples))


class ProductWorkflowTests(TestCase):
    def deal(self,title='코카콜라 제로 355ml 24캔',price=12000,currency='WON'):
        deal=Deal.objects.create(subject=title,price=price,currency=currency,community_name='TEST',
            write_at=timezone.now()-timedelta(days=2),crawled_at=timezone.now())
        with transaction.atomic():jobs.seed(deal,historical=True)
        return deal

    def resolve(self,deal):
        job=DealProduct.objects.get(pk=deal.pk);jobs.process_rule(job)
        return DealProduct.objects.get(pk=deal.pk)

    def test_missing_container_reuses_the_unique_format_and_keeps_raw_evidence(self):
        can=self.resolve(self.deal('코카콜라 190ml 캔'))
        missing=self.resolve(self.deal('코카콜라 190ml 24개'))
        pack=self.resolve(self.deal('코카콜라 190ml 48캔'))
        self.assertEqual({can.product_id,missing.product_id,pack.product_id},{can.product_id})
        self.assertNotIn('container',missing.extraction['attributes'])
        self.assertEqual(Product.objects.count(),1)

    def test_first_explicit_container_enriches_the_existing_uuid(self):
        missing=self.resolve(self.deal('코카콜라 190ml'))
        can=self.resolve(self.deal('코카콜라 190ml 캔'))
        self.assertEqual(can.product_id,missing.product_id)
        self.assertEqual(can.product.attributes['container'],'can')
        self.assertIn('캔',can.product.name)
        self.assertEqual(ProductPrice.objects.get(deal_id=missing.pk).product_id,can.product_id)

    def test_conflicting_containers_sizes_and_flavors_are_not_inferred(self):
        can=self.resolve(self.deal('코카콜라 190ml 캔'))
        pet=self.resolve(self.deal('코카콜라 190ml 페트'))
        missing=self.resolve(self.deal('코카콜라 190ml'))
        large=self.resolve(self.deal('코카콜라 355ml'))
        zero=self.resolve(self.deal('코카콜라 제로 190ml'))
        self.assertEqual(len({row.product_id for row in [can,pet,missing,large,zero]}),5)
        self.assertNotIn('container',missing.product.attributes)

    def test_legacy_unknown_product_with_conflicting_container_history_is_not_reused(self):
        missing=self.resolve(self.deal('코카콜라 350ml 24개'))
        can=self.resolve(self.deal('코카콜라 캔 350ml 24개'))
        self.assertEqual(missing.product_id,can.product_id)

        # Recreate the legacy state found in production: the catalog key lost its
        # container even though one linked title still explicitly says "can".
        generic=identity.canonical_data(can.extraction)
        generic['attributes'].pop('container',None)
        legacy=Product.objects.get(pk=can.product_id)
        legacy.identity_key=identity.signature(generic)
        legacy.attributes=generic['attributes']
        legacy.name=identity.display_name(generic)
        legacy.save(update_fields=['identity_key','attributes','name'])

        pet_deal=self.deal('코카콜라 350ml 페트 20개')
        pet_job=DealProduct.objects.get(pk=pet_deal.pk)
        pet_data={'brand':'코카콜라','name':'코카콜라','model':'','variant':'',
                  'attributes':identity.facts(pet_deal.subject),'category':'food'}
        linked=jobs.resolve(pet_job,pet_data,'llm',target=legacy)
        self.assertEqual(linked,1)
        pet=DealProduct.objects.get(pk=pet_deal.pk)
        self.assertNotEqual(pet.product_id,legacy.pk)
        self.assertEqual(pet.product.attributes['container'],'pet')
        legacy.refresh_from_db()
        self.assertNotIn('container',legacy.attributes)

    def test_verified_unknown_container_is_not_rewritten(self):
        missing=self.resolve(self.deal('코카콜라 190ml'))
        Product.objects.filter(pk=missing.product_id).update(verified=True)
        can=self.resolve(self.deal('코카콜라 190ml 캔'))
        self.assertNotEqual(can.product_id,missing.product_id)
        missing.product.refresh_from_db()
        self.assertNotIn('container',missing.product.attributes)

    def test_seed_idempotence_and_cross_post_price_history(self):
        a,b=self.deal(),self.deal('코카콜라 제로 355ml 48캔',22000)
        with transaction.atomic():jobs.seed(a,historical=True)
        aa,bb=self.resolve(a),self.resolve(b)
        jobs.process_prices()
        self.assertEqual(aa.product_id,bb.product_id)
        self.assertEqual(ProductPrice.objects.count(),2)
        result=history(aa.product,{'basis':'item'})
        self.assertEqual({p['amount'] for p in result['points']},{'500','458.33'})

    def test_late_model_result_cannot_overwrite_manual_connection(self):
        deal=self.deal();stale=DealProduct.objects.get(pk=deal.pk)
        product=Product.objects.create(identity_key='manual',name='수동 상품')
        jobs.manual_assign(deal.pk,product,'operator',1)
        self.assertEqual(jobs.resolve(stale,identity.extract_rule(deal.subject),'llm'),0)
        self.assertEqual(DealProduct.objects.get(pk=deal.pk).product_id,product.pk)

    def test_title_change_generation_keeps_old_prices(self):
        deal=self.deal();old=self.resolve(deal)
        newer=Product.objects.create(identity_key='newer',name='다른 상품')
        DealProduct.objects.filter(pk=deal.pk).update(identity_revision=2,request_revision=2,price_revision=2)
        ProductPrice.objects.create(deal=deal,identity_revision=2,price_revision=2,published_at=timezone.now(),input={'price':20})
        jobs.manual_assign(deal.pk,newer,'operator',2)
        self.assertEqual(ProductPrice.objects.get(deal=deal,price_revision=1).product_id,old.product_id)
        self.assertEqual(ProductPrice.objects.get(deal=deal,price_revision=2).product_id,newer.pk)
        with self.assertRaises(ValueError):jobs.manual_assign(deal.pk,old.product,'operator',2)

    def test_model_unavailable_keeps_pending_work_and_does_not_use_retries(self):
        deal=self.deal('로지텍 MX Master 4 무선 마우스');job=DealProduct.objects.get(pk=deal.pk)
        jobs.process_rule(job);job.refresh_from_db()
        model=Mock();model.structured.side_effect=Unavailable('stopped')
        jobs.process_llm(job,model);job.refresh_from_db()
        self.assertEqual((job.status,job.attempts),('llm',0))

    def test_model_capacity_wait_is_not_a_manual_review_and_cannot_spin(self):
        for i in range(42):self.deal('로지텍 새로운 상품 '+str(i))
        self.assertEqual(jobs.process_rules(limit=50),42)
        self.assertEqual(DealProduct.objects.filter(status='llm').count(),40)
        self.assertEqual(DealProduct.objects.filter(status='pending',last_error='awaiting_model_capacity').count(),2)
        self.assertEqual(jobs.process_rules(),0)
        DealProduct.objects.filter(status='llm').first().delete()
        jobs.refill_model_queue()
        self.assertEqual(DealProduct.objects.filter(status='llm').count(),40)

    def test_model_output_links_real_product_and_records_work(self):
        deal=self.deal('로지텍 MX Master 4 무선 마우스');job=DealProduct.objects.get(pk=deal.pk)
        model=Mock();model.structured.return_value={'is_product':True,'brand':'로지텍','name':'MX Master 4','model':'MX Master 4','variant':'','category':'computer'}
        jobs.process_llm(job,model);job.refresh_from_db()
        self.assertEqual((job.status,job.source),('ready','llm'))
        self.assertEqual(ClassificationState.objects.get(pk='products:model').value['linked'],1)

    def test_model_cache_reuses_product_across_price_and_pack_count_changes(self):
        first=self.deal('매일두유 검은콩 190ml 24팩 (12,000원/무료)')
        second=self.deal('매일두유 검은콩 190ml 48팩 (22,000원/무료)')
        model=Mock();model.structured.return_value={'is_product':True,'brand':'매일','name':'매일두유','model':'','variant':'검은콩','category':'food'}
        jobs.process_llm(DealProduct.objects.get(pk=first.pk),model)
        jobs.process_llm(DealProduct.objects.get(pk=second.pk),model)
        self.assertEqual(model.structured.call_count,1)
        self.assertEqual(DealProduct.objects.get(pk=first.pk).product_id,DealProduct.objects.get(pk=second.pk).product_id)
        self.assertEqual(ClassificationState.objects.get(pk='products:model').value['cache_hits'],1)

    def test_manual_feedback_becomes_reviewed_alias_and_negative_example(self):
        deal=self.deal();job=self.resolve(deal)
        other=Product.objects.create(identity_key='other',name='검토된 상품',attributes=identity.facts(deal.subject))
        jobs.manual_assign(deal.pk,other,'reviewer',job.request_revision)
        self.assertEqual(ProductMatchExample.objects.filter(same_product=False).count(),1)
        self.assertEqual(jobs.reviewed_alias(deal.subject).pk,other.pk)
        changed=self.deal('코카콜라 제로 355ml 48캔')
        self.assertEqual(self.resolve(changed).source,'learned')

    def test_learning_is_versioned_idempotent_and_excludes_model_guesses(self):
        bootstrap.install();version=learning.train_stored()
        self.assertEqual(learning.train_stored(),version)
        self.assertEqual(ProductMatcherVersion.objects.count(),1)
        self.assertEqual(ProductMatcherVersion.objects.get().example_count,64)

    def test_installing_examples_again_does_not_overwrite_operator_feedback(self):
        row=next(bootstrap.examples())
        jobs.add_example(row['left_title'],row['right_title'],False,actor='reviewer')
        bootstrap.install()
        saved=ProductMatchExample.objects.get(left_title=row['left_title'],right_title=row['right_title'])
        self.assertFalse(saved.same_product);self.assertEqual(saved.origin,'operator')

    def test_repair_keeps_valid_uuid_and_requeues_wrong_llm_result(self):
        from gadmin.products.repair import repair
        deal=self.deal();valid=self.resolve(deal)
        DealProduct.objects.filter(pk=deal.pk).update(processor_version='products-1/product-extract-1')
        other=self.deal('매일두유 검은콩 190ml 48팩');bad=Product.objects.create(identity_key='bad-auto',name='두유 190ml')
        DealProduct.objects.filter(pk=other.pk).update(product=bad,status='ready',source='llm',processor_version='products-1/product-extract-1')
        ProductPrice.objects.filter(deal=other).update(product=bad)
        result=repair()
        self.assertEqual(result['reprocessed'],2)
        self.assertEqual(DealProduct.objects.get(pk=deal.pk).product_id,valid.product_id)
        self.assertIsNone(DealProduct.objects.get(pk=other.pk).product_id)
        self.assertEqual(ProductPrice.objects.count(),2)
        self.assertFalse(Product.objects.filter(pk=bad.pk).exists())

    def test_history_keeps_currency_and_conditional_prices_out_of_graph(self):
        deal=self.deal();job=self.resolve(deal);jobs.process_prices()
        price=ProductPrice.objects.get(deal=deal)
        ProductPrice.objects.create(deal=deal,product=job.product,identity_revision=1,price_revision=2,
            published_at=price.published_at,input={},result={'price':{'amount':'20','currency':'USD'},'warnings':[]},processed_at=timezone.now())
        self.assertEqual(len(history(job.product,{'basis':'offer','currency':'KRW'})['points']),1)
        self.assertEqual(history(job.product,{'basis':'offer','currency':'USD'})['points'][0]['amount'],'20')
        self.assertEqual(history(job.product,{'basis':'offer','currency':'KRW','shipping':'1'})['points'],[])
        price.result['warnings'].append('conditional_price');price.save()
        self.assertEqual(history(job.product,{'basis':'offer','currency':'KRW'})['points'],[])

    @tag('web')
    def test_read_only_api_and_admin_permission_filters(self):
        deal=self.deal();job=self.resolve(deal);jobs.process_prices()
        url=f'/api/products/{job.product_id}/history/'
        self.assertEqual(self.client.get(url).status_code,200)
        self.assertEqual(self.client.get(url,{'start':'invalid'}).status_code,400)
        self.assertEqual(self.client.post(f'/api/products/{job.product_id}/',{}).status_code,405)
        admin_url=reverse('admin:deals_product_history',args=[job.product_id])
        self.assertEqual(self.client.get(admin_url).status_code,302)
        user=get_user_model().objects.create_user(username='staff',is_staff=True)
        self.client.force_login(user)
        self.assertEqual(self.client.get(admin_url).status_code,403)
        user.is_superuser=True;user.save()
        self.assertContains(self.client.get(admin_url),'게시물과 가격 기록')
        self.assertEqual(self.client.get(admin_url,{'start':'2026-09-20','end':'2026-09-01'}).status_code,400)
