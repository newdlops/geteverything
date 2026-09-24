from datetime import timedelta
import json
from pathlib import Path
import tempfile
from unittest.mock import Mock
import uuid

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from gadmin.deals.models import Deal, DealProduct, Product, ProductPrice
from gadmin.products import identity, jobs
from gadmin.products.deduplicate import deduplicate


class StableIdentityTests(SimpleTestCase):
    def test_full_model_code_ignores_marketing_and_redundant_specs(self):
        groups=[['9800X3D 멀티팩','AMD 라이젠7-6세대 9800X3D (그래니트 릿지) (멀티팩 정품)',
                 'AMD 라이젠7 9800X3D 멀티팩 정품 + 붉은사막 증정'],
                ['LG 울트라기어 32GX870A','[네이버] 출시 D-4 LG 32GX870A 32인치 4K 240Hz 올레드 모니터',
                 'LG 32GX870A 9/18 한정 특가']]
        for titles in groups:
            self.assertEqual(len({identity.signature(identity.extract_rule(title)) for title in titles}),1)
        self.assertNotIn('red',identity.facts('올레드 모니터 16스레드')['options'])

    def test_pack_capacity_condition_and_accessories_keep_boundaries(self):
        for left,right in [('삼성 990 PRO 1TB','삼성 990 PRO 2TB'),
                           ('AMD 9800X3D','AMD 9800X3D 리퍼 중고'),
                           ('코카콜라 제로 190ml 30캔','코카콜라 제로 라임 190ml 30캔'),
                           ('코카콜라 제로 190ml 30캔','코카콜라 제로 355ml 30캔')]:
            self.assertNotEqual(identity.signature(identity.extract_rule(left)),identity.signature(identity.extract_rule(right)))
        self.assertIsNone(identity.extract_rule('삼성 990 PRO 1TB 호환 방열판'))
        self.assertEqual(identity.signature(identity.extract_rule('코카콜라 제로 190ml 30캔')),
                         identity.signature(identity.extract_rule('코카콜라 제로 190ml 60캔')))

    def test_pc_bundles_and_multi_model_events_never_become_single_component(self):
        for title in ['9800X3D + 5070TI+32GB+1TB 완본체 (하이마트 PLUX PC)',
                      '[아싸컴] 9800X3D + 5080 뱅가드 완본체',
                      'AMD 9800X3D+RX9070XT 16GB+32GB+1TB',
                      '서린컴퓨터 9800X3D_RTX5080 16GB_RAM 32GB_프렉탈 Epoch RGB',
                      '9800x3d 5080 96gb램 완본',
                      'AMD 9600X, 9800X3D 특가',
                      'AMD 라이젠 7800X3D, 9800X3D+붉은사막증정',
                      'LG 32GS75Q / 27G810A / 32U880SAW 등 6종',
                      'LG 27GX700A(83만)/4K모니터 27US55…',
                      'LG 32GS75Q 특가 10종 LG모니터 할인정리']:
            self.assertIsNone(identity.extract_rule(title),title)
            self.assertIsNone(identity.grounded(title,{'is_product':True,'brand':'AMD','name':'9800X3D','model':'9800X3D'})[0],title)

    def test_names_show_actual_variants(self):
        name=identity.display_name(identity.extract_rule('코카콜라 제로 라임 355ml 48캔'))
        for value in ['제로','라임','355ml','캔']:self.assertIn(value,name)
        self.assertNotIn('48',name)
        self.assertNotEqual(name,identity.display_name(identity.extract_rule('코카콜라 제로 190ml 30캔')))
        self.assertEqual(identity.signature(identity.extract_rule('코카콜라 제로 350ml 24 (15,610원/무배)')),
                         identity.signature(identity.extract_rule('코카콜라 제로 350ml 24개')))
        self.assertNotEqual(identity.signature(identity.extract_rule('코카콜라 제로 350ml 24입')),
                            identity.signature(identity.extract_rule('코카콜라 제로-제로 350ml 24입')))
        for title in ['코카콜라 오리지널/제로 190ml 30캔','코카콜라 제로 490ml 24/48캔']:
            self.assertIsNone(identity.extract_rule(title))


class DeduplicateTests(TestCase):
    def legacy(self,title,*,product=None,revision=1):
        data=identity.extract_rule(title)
        if product is None:
            model=(identity.KNOWN_MODEL.search(identity.normalize(title)))
            model=model.group() if model else ''
            product=Product.objects.create(identity_key=str(uuid.uuid4()),name=model or '코카콜라',model=model,
                brand='AMD' if model.endswith('x3d') else '',attributes=identity.facts(title))
        deal=Deal.objects.create(subject=title,price=10000,currency='WON',community_name='TEST',write_at=timezone.now())
        with transaction.atomic():jobs.seed(deal)
        DealProduct.objects.filter(pk=deal.pk).update(product=product,status='ready',source='rule',
            extraction=data or {},processor_version='products-3/product-extract-2',identity_revision=revision)
        ProductPrice.objects.filter(deal=deal).update(product=product,identity_revision=revision,
            result={'price':{'amount':'10000','currency':'KRW'},'warnings':[]},processed_at=timezone.now())
        return product,deal

    def apply(self):
        with tempfile.TemporaryDirectory() as directory:
            result=deduplicate(apply=True,backup=Path(directory)/'backup.json')
            saved=json.loads(Path(result['backup']).read_text())
            self.assertEqual(saved['summary']['price_payload_sha256'],result['price_payload_sha256'])
            return result

    def test_missing_container_merges_existing_history_without_inventing_title_evidence(self):
        first,a=self.legacy('코카콜라 190ml 24개')
        second,b=self.legacy('코카콜라 190ml 48캔')
        zero,c=self.legacy('코카콜라 제로 190ml 30캔')
        before=list(ProductPrice.objects.order_by('pk').values('id','input','result','published_at','observed_at'))
        result=self.apply()
        self.assertEqual((result['active_after'],result['merged']),(2,1))
        aa=DealProduct.objects.get(pk=a.pk);bb=DealProduct.objects.get(pk=b.pk)
        self.assertEqual(aa.product_id,bb.product_id)
        self.assertNotEqual(aa.product_id,DealProduct.objects.get(pk=c.pk).product_id)
        self.assertNotIn('container',aa.extraction['attributes'])
        self.assertEqual(aa.product.attributes['container'],'can')
        self.assertEqual(before,list(ProductPrice.objects.order_by('pk').values('id','input','result','published_at','observed_at')))
        again=self.apply()
        self.assertEqual((again['products_updated'],again['assignments_updated'],again['prices_moved']),(0,0,0))

    def test_conflicting_container_evidence_splits_old_inference_and_keeps_explicit_uuid(self):
        data=identity.extract_rule('코카콜라 190ml 캔')
        can=Product.objects.create(identity_key=identity.signature(data),name=identity.display_name(data),
            brand=data['brand'],attributes=data['attributes'])
        _,a=self.legacy('코카콜라 190ml 캔',product=can)
        _,b=self.legacy('코카콜라 190ml 24개',product=can)
        pet,c=self.legacy('코카콜라 190ml 페트')
        result=self.apply()
        self.assertEqual(result['active_after'],3)
        self.assertEqual(DealProduct.objects.get(pk=a.pk).product_id,can.pk)
        missing=DealProduct.objects.get(pk=b.pk)
        self.assertNotIn('container',missing.product.attributes)
        self.assertEqual(len(set(DealProduct.objects.values_list('product_id',flat=True))),3)
        again=self.apply()
        self.assertEqual((again['products_updated'],again['prices_moved']),(0,0))

    def test_scoped_repair_splits_conflicting_container_history_without_touching_other_products(self):
        legacy,a=self.legacy('코카콜라 350ml 24개')
        _,b=self.legacy('코카콜라 캔 350ml 24개',product=legacy)
        _,c=self.legacy('코카콜라 350ml 페트 20개',product=legacy)
        unrelated,d=self.legacy('AMD 9800X3D')
        original_prices=list(ProductPrice.objects.order_by('pk').values('id','input','result','published_at','observed_at'))
        preview=deduplicate(product_ids=[legacy.pk])
        self.assertEqual(preview['scope_product_ids'],[str(legacy.pk)])
        self.assertGreaterEqual(preview['assignments_updated'],2)
        self.assertEqual(Product.objects.filter(pk=unrelated.pk,is_active=True).count(),1)
        with tempfile.TemporaryDirectory() as directory:
            result=deduplicate(apply=True,backup=Path(directory)/'scoped.json',product_ids=[legacy.pk])
            saved=json.loads(Path(result['backup']).read_text())
        self.assertEqual(saved['summary']['price_payload_sha256'],result['price_payload_sha256'])
        self.assertNotEqual(DealProduct.objects.get(pk=b.pk).product_id,DealProduct.objects.get(pk=c.pk).product_id)
        self.assertNotEqual(DealProduct.objects.get(pk=a.pk).product_id,DealProduct.objects.get(pk=b.pk).product_id)
        self.assertEqual(DealProduct.objects.get(pk=d.pk).product_id,unrelated.pk)
        self.assertEqual(list(ProductPrice.objects.order_by('pk').values('id','input','result','published_at','observed_at')),
                         original_prices)

    def test_scoped_repair_unifies_same_title_alias_with_differently_partitioned_fields(self):
        left_title='펩시콜라 제로슈거 라임 310ml 24캔'
        right_title='펩시콜라 제로슈거 라임 310ml 48캔'
        left,left_deal=self.legacy(left_title)
        right,right_deal=self.legacy(right_title)
        shared=identity.facts(left_title)
        extractions=[
            {'brand':'펩시콜라','name':'제로슈거 라임','model':'','variant':'','attributes':shared},
            {'brand':'펩시','name':'펩시콜라 제로슈거','model':'','variant':'라임','attributes':shared},
        ]
        for deal,data in ((left_deal,extractions[0]),(right_deal,extractions[1])):
            DealProduct.objects.filter(pk=deal.pk).update(extraction=data)
        preview=deduplicate(product_ids=[left.pk,right.pk])
        self.assertEqual(preview['merged'],1)
        with tempfile.TemporaryDirectory() as directory:
            result=deduplicate(apply=True,backup=Path(directory)/'aliases.json',product_ids=[left.pk,right.pk])
            saved=json.loads(Path(result['backup']).read_text())
        self.assertTrue(result['price_payload_preserved'])
        self.assertEqual(saved['summary']['price_payload_sha256'],result['price_payload_sha256'])
        self.assertEqual(DealProduct.objects.get(pk=left_deal.pk).product_id,
                         DealProduct.objects.get(pk=right_deal.pk).product_id)
        for deal in (left_deal,right_deal):
            job=DealProduct.objects.get(pk=deal.pk)
            self.assertEqual(identity.signature(job.extraction),job.product.identity_key)
        self.assertEqual(ProductPrice.objects.filter(product_id=left.pk).count()+
                         ProductPrice.objects.filter(product_id=right.pk).count(),2)
        again=deduplicate(product_ids=[left.pk,right.pk])
        self.assertEqual((again['products_updated'],again['assignments_updated'],again['prices_moved']),(0,0,0))

    def test_merge_keeps_uuid_raw_prices_old_links_and_future_posts_reuse_identity(self):
        first,a=self.legacy('AMD 9800X3D')
        second,b=self.legacy('AMD 라이젠7-6세대 9800X3D 멀티팩 정품 + 붉은사막 증정')
        original=list(ProductPrice.objects.order_by('id').values('id','input','result','published_at','observed_at'))
        preview=deduplicate()
        self.assertEqual((preview['active_after'],preview['merged']),(1,1))
        self.assertEqual(Product.objects.filter(is_active=True).count(),2)
        result=self.apply()
        self.assertTrue(result['price_payload_preserved'])
        second.refresh_from_db()
        self.assertEqual(second.merged_into_id,first.pk)
        self.assertFalse(second.is_active)
        self.assertEqual(set(DealProduct.objects.values_list('product_id',flat=True)),{first.pk})
        self.assertEqual(set(ProductPrice.objects.values_list('product_id',flat=True)),{first.pk})
        self.assertEqual(original,list(ProductPrice.objects.order_by('id').values('id','input','result','published_at','observed_at')))
        again=self.apply()
        self.assertEqual((again['products_updated'],again['assignments_updated'],again['prices_moved']),(0,0,0))
        deal=Deal.objects.create(subject='9800X3D 멀티팩',price=11000,currency='WON')
        with transaction.atomic():job=jobs.seed(deal)
        jobs.process_rule(job)
        self.assertEqual(DealProduct.objects.get(pk=deal.pk).product_id,first.pk)
        response=self.client.get('/api/products/')
        self.assertEqual(len(response.json()['results']),1)
        self.assertEqual(self.client.get(f'/api/products/{second.pk}/').json()['id'],str(first.pk))
        user=get_user_model().objects.create_superuser(username='operator',password='test')
        self.client.force_login(user)
        response=self.client.get(reverse('admin:deals_product_history',args=[second.pk]),{'basis':'item'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(response.url,reverse('admin:deals_product_history',args=[first.pk])+'?basis=item')

    def test_mixed_offer_prices_detach_and_old_title_revisions_are_not_relabelled(self):
        cpu,a=self.legacy('AMD 9800X3D')
        pc,b=self.legacy('9800X3D + 5070TI+32GB+1TB 완본체')
        old,c=self.legacy('AMD 7800X3D')
        history=ProductPrice.objects.create(deal=a,product=cpu,identity_revision=0,price_revision=0,
            published_at=timezone.now()-timedelta(days=5),input={'subject':'AMD 7800X3D','price':9000})
        original_count=ProductPrice.objects.count()
        result=self.apply()
        self.assertEqual((result['assignments_detached'],result['prices_detached']),(1,1))
        pc.refresh_from_db();self.assertFalse(pc.is_active);self.assertIsNone(pc.merged_into_id)
        self.assertEqual(DealProduct.objects.get(pk=b.pk).status,'review')
        self.assertIsNone(ProductPrice.objects.get(deal=b).product_id)
        history.refresh_from_db();self.assertEqual(history.product_id,old.pk)
        self.assertEqual(ProductPrice.objects.count(),original_count)
        jobs.process_rule(DealProduct.objects.get(pk=b.pk))
        self.assertIsNone(DealProduct.objects.get(pk=b.pk).product_id)

    def test_manual_and_verified_decisions_are_preserved(self):
        manual,a=self.legacy('9800X3D + 5070TI+32GB+1TB 완본체')
        DealProduct.objects.filter(pk=a.pk).update(manual_override=True,source='manual')
        verified,b=self.legacy('AMD 9800X3D');verified.verified=True;verified.save()
        before=list(ProductPrice.objects.order_by('id').values())
        result=self.apply()
        self.assertEqual(result['protected_products'],2)
        self.assertEqual(list(ProductPrice.objects.order_by('id').values()),before)
        self.assertEqual(Product.objects.filter(is_active=True).count(),2)

    def test_late_llm_result_cannot_reintroduce_pc_component_link(self):
        product,deal=self.legacy('9800X3D + 5070TI+32GB+1TB 완본체')
        job=DealProduct.objects.get(pk=deal.pk)
        model=Mock()
        jobs.process_llm(job,model)
        self.assertFalse(model.structured.called)
        self.assertIsNone(DealProduct.objects.get(pk=deal.pk).product_id)
        jobs.resolve(job,identity.extract_rule('AMD 9800X3D'),'llm')
        self.assertIsNone(DealProduct.objects.get(pk=deal.pk).product_id)
