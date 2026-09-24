from datetime import datetime, timezone as datetime_timezone

from django.test import SimpleTestCase, TestCase

from gadmin.deals.models import ClassificationState

from gadmin.products import identity, quality


class ProductQualityTests(SimpleTestCase):
    def test_review_candidates_distinguish_reply_numbers_from_real_sku_boundaries(self):
        def product(pk, size, numeric=(), *, brand='펩시', name='제로슈거 라임'):
            return {'id':pk, 'brand':brand, 'name':name, 'model':'',
                    'attributes':{'sizes':['volume_ml:'+size], 'options':['lime','zero'],
                                  'specs':[], 'container':'can', 'numeric_options':list(numeric)}}
        products=[product(1,'310',('13',)),product(2,'310',('8',)),
                  product(3,'310'),product(4,'355')]
        assignments=[
            {'product_id':1,'input_title':'펩시 제로슈거 라임 310ml 24캔 [13]',
             'extraction':{'attributes':products[0]['attributes']}},
            {'product_id':2,'input_title':'펩시 제로슈거 라임 310ml 48캔 [8]',
             'extraction':{'attributes':products[1]['attributes']}},
            {'product_id':3,'input_title':'펩시 제로슈거 라임 310ml 24캔',
             'extraction':{'attributes':products[2]['attributes']}},
            {'product_id':3,'input_title':'펩시 제로슈거 라임 310ml 48캔',
             'extraction':{'attributes':products[2]['attributes']}},
            {'product_id':4,'input_title':'펩시 제로슈거 라임 355ml 24캔',
             'extraction':{'attributes':products[3]['attributes']}},
        ]
        summary=quality.summarize(products, assignments)
        self.assertEqual(summary['reply_count_as_identity_option'],2)
        self.assertEqual(summary['numeric_split_review_groups'],1)
        self.assertEqual(summary['numeric_split_review_products'],3)
        self.assertEqual(summary['numeric_split_review_assignments'],4)
        self.assertEqual(summary['products_with_multiple_pack_counts'],1)
        self.assertEqual(summary['cross_post_conflict_products'],0)
        self.assertNotIn('4',summary['review_candidates'][0]['product_ids'])
        self.assertEqual(identity.facts(assignments[0]['input_title'])['numeric_options'],[])

    def test_review_audit_keeps_promotion_leak_and_duplicate_keys_as_candidates(self):
        attributes={'sizes':[], 'specs':['16gb'], 'options':[], 'numeric_options':['5080']}
        products=[{'id':1,'brand':'G마켓','name':'G마켓 COLORFUL iGame 지포스 16GB',
                   'model':'','attributes':attributes},
                  {'id':2,'brand':'삼성','name':'갤럭시 S25 256GB','model':'S25','attributes':attributes},
                  {'id':3,'brand':'삼성','name':'갤럭시 S25 256GB','model':'S25','attributes':attributes}]
        summary=quality.summarize(products, [], example_limit=0)
        self.assertEqual(summary['shop_brand_products'],1)
        self.assertEqual(summary['same_signature_review_groups'],1)
        self.assertEqual(summary['same_signature_review_products'],2)
        self.assertEqual(summary['review_candidates'],[])

    def test_conflicting_sizes_and_options_within_one_product_are_flagged(self):
        product={'id':1,'brand':'펩시','name':'제로슈거','model':'',
                 'attributes':{'sizes':['volume_ml:310'],'options':['zero','lime'],
                               'specs':[],'numeric_options':[]}}
        def row(title,size,flavor,count):
            return {'product_id':1,'input_title':f'{title} {size}ml {count}캔',
                    'extraction':{'brand':'펩시','name':'제로슈거',
                        'attributes':{'sizes':[f'volume_ml:{size}'],
                                      'options':['zero',flavor],'container':'can'}}}
        same=quality.summarize([product],[row('펩시 제로슈거 라임',310,'lime',24),
                                          row('펩시 제로슈거 라임',310,'lime',48)])
        self.assertEqual(same['cross_post_conflict_products'],0)
        changed=quality.summarize([product],[row('펩시 제로슈거 라임',310,'lime',24),
                                             row('펩시 제로슈거 레몬',355,'lemon',48)])
        self.assertEqual(changed['cross_post_conflicts']['size'],1)
        self.assertEqual(changed['cross_post_conflicts']['flavor'],1)
        self.assertEqual(changed['cross_post_conflict_products'],1)


class ProductQualityRecordingTests(TestCase):
    def test_daily_snapshots_replace_same_day_and_keep_bounded_history(self):
        summary={key:0 for key in quality.TREND_KEYS}
        summary.update(version='products-7',review_candidates=[{'product_ids':['example']}])
        first=datetime(2026,9,24,12,tzinfo=datetime_timezone.utc)
        quality.record(summary,now=first)
        updated=quality.record(summary|{'active_products':5},now=first)
        self.assertEqual(len(updated['history']),1)
        self.assertEqual(updated['history'][0]['active_products'],5)
        self.assertEqual(updated['review_candidates'],summary['review_candidates'])
        state=ClassificationState.objects.get(key='products:quality')
        state.value={'history':[{'date':f'2026-01-{day:02d}'} for day in range(1,32)]*3}
        state.save(update_fields=['value'])
        latest=quality.record(summary|{'active_products':6},now=first)
        self.assertEqual(len(latest['history']),90)
        self.assertEqual(latest['history'][-1]['active_products'],6)

    def test_daily_boundary_uses_korea_time_even_when_worker_uses_utc(self):
        summary={key:0 for key in quality.TREND_KEYS}
        moment=datetime(2026,9,24,15,30,tzinfo=datetime_timezone.utc)
        snapshot=quality.record(summary,now=moment)
        self.assertEqual(snapshot['history'][-1]['date'],'2026-09-25')
