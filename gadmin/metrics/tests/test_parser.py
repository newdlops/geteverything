import unittest
from gadmin.metrics.parser import analyze, quantities
from gadmin.metrics.money import legacy_subject_price


class QuantityTests(unittest.TestCase):
    def test_mass_volume_and_nested_counts(self):
        cases = [('물 500ml x 24개','volume_ml','12000'),('치킨피자 200g 5팩','weight_g','1000'),
                 ('우삼겹 250g X 6팩 (총 1.5kg)','weight_g','1500'),('콜라 210mlx30캔','volume_ml','6300'),
                 ('콜라 2L 6병 x 2팩','volume_ml','24000'),('음료 500ml 1+1','volume_ml','1000')]
        for title,key,total in cases:
            with self.subTest(title=title):
                self.assertEqual(quantities(title)[key]['total'],total)
        self.assertEqual(quantities('물티슈 40매 16팩')['quantity']['count'],'640')
        self.assertEqual(quantities('미용티슈 250매 x 3입 x 4팩 총 12개')['quantity']['count'],'3000')
        self.assertEqual(quantities('물티슈 80매 총 20팩')['quantity']['count'],'1600')
        self.assertEqual(quantities('탄산수 500ml 1박스 20입')['quantity']['unit'],'입')
        self.assertEqual(quantities('탄산수 500ml 1박스 20입')['volume_ml']['total'],'10000')

    def test_strength_and_device_specs_are_not_package_mass(self):
        for title in ['비타민 1000mg 60정','NVME SSD 512g','RTX 5070 12GB','노트북 16GB 512GB']:
            with self.subTest(title=title):
                self.assertIsNone(quantities(title)['weight_g'])
        self.assertEqual(quantities('비타민 1000mg 60정')['quantity']['count'],'60')
        result=quantities('영양 음료 200ml 24팩 단백질 16g')
        self.assertIsNone(result['weight_g'])
        self.assertEqual(result['volume_ml']['total'],'4800')

    def test_mixed_sizes_ranges_and_unknown_multipliers_abstain(self):
        for title in ['쌀 10kg 20kg 골라담기','음료 500ml 2개 + 1L 1개','고구마 3~5kg','생수 500ml 2~4개']:
            with self.subTest(title=title):
                parsed=quantities(title)
                self.assertIsNone(parsed['weight_g'])
                self.assertIsNone(parsed['volume_ml'])
                self.assertTrue(parsed['warnings'])
        self.assertFalse(analyze({'subject':'음료 500ml 2팩 + 1L 1팩 (12,000원/무료)'})['unit_prices'])

    def test_gift_and_stated_totals_do_not_double_count(self):
        self.assertEqual(quantities('코카콜라 350ml 24캔 + 달력 1개 증정')['volume_ml']['total'],'8400')
        self.assertIsNone(quantities('쌀 500g 2팩 (총 3kg)')['weight_g'])

    def test_package_count_is_not_money(self):
        for title in ['햇반 210g 36입','콜라 355ml 24캔','세제 200개입','비타민 1000mg 60정','신제품 2026']:
            self.assertEqual(legacy_subject_price(title),0)

    def test_paper_density_and_inner_package_weight_are_not_multiplied(self):
        paper=quantities('A4 복사용지 80g 500매 5권')
        self.assertIsNone(paper['weight_g'])
        self.assertEqual(paper['quantity']['count'],'2500')
        self.assertIsNone(quantities('소시지 600g 10개입')['weight_g'])
        self.assertEqual(quantities('소시지 60g x10개입')['weight_g']['total'],'600')

    def test_stated_total_and_ambiguous_same_level_counts(self):
        self.assertEqual(quantities('포장육 각 500g 총 2kg')['weight_g']['total'],'2000')
        self.assertIsNone(quantities('라면 2팩+3팩')['quantity'])

    def test_container_capacity_is_not_contents_for_unit_price(self):
        result=analyze({'subject':'텀블러 600ml 1개','numeric_evidence':{'price':'7,250원'}})
        self.assertIsNone(result['volume_ml'])
        self.assertEqual(result['capacity_ml']['per_item'],'600')
        self.assertEqual(len(result['unit_prices']),1)
        self.assertEqual(result['unit_prices'][0]['basis_unit'],'개')
        self.assertEqual(result['unit_prices'][0]['amount'],'7250')

    def test_vessel_gift_and_cleaner_still_use_real_contents(self):
        self.assertEqual(quantities('생수 500ml 24개 + 텀블러 증정')['volume_ml']['total'],'12000')
        self.assertEqual(quantities('텀블러 세정제 500ml 2개')['volume_ml']['total'],'1000')


class PriceTests(unittest.TestCase):
    def test_unit_price_and_shipping_are_separate(self):
        result=analyze({'subject':'생수 500ml 24개 (12,000원/3,000원)'})
        self.assertEqual(result['volume_ml']['total'],'12000')
        volume=result['unit_prices'][0]
        self.assertEqual(volume['amount'],'100')
        self.assertEqual(volume['amount_with_shipping'],'125')
        self.assertEqual(result['total_price_with_shipping'],'15000')

    def test_zero_default_never_means_free_shipping_or_product(self):
        result=analyze({'subject':'물 500ml 24캔','price':24,'currency':None,'delivery_price':0})
        self.assertIsNone(result['price'])
        self.assertIsNone(result['shipping'])
        self.assertFalse(result['unit_prices'])
        self.assertIn('legacy_price_ignored',result['warnings'])

    def test_structured_price_retains_foreign_decimals(self):
        result=analyze({'subject':'프로틴 500g 2팩','price':19,'currency':'USD','numeric_evidence':{'price':'$19.99','delivery':'무료'}})
        self.assertEqual(result['price']['amount'],'19.99')
        self.assertEqual(result['price']['source'],'collected_price')
        self.assertEqual(result['total_price_with_shipping'],'19.99')
        self.assertNotIn('legacy_foreign_precision',result['warnings'])

    def test_old_foreign_precision_is_visible(self):
        result=analyze({'subject':'스피커','price':19,'currency':'USD'})
        self.assertIn('legacy_foreign_precision',result['warnings'])

    def test_unknown_currency_and_shipping_threshold_do_not_invent_totals(self):
        result=analyze({'subject':'상품 500g ($19.99/무료)'})
        self.assertIsNone(result['price']['currency'])
        self.assertFalse(result['unit_prices'])
        threshold=analyze({'subject':'가래떡500g (5,520원/15,000원무료)'})
        self.assertIsNone(threshold['shipping'])
        self.assertIsNone(threshold['total_price_with_shipping'])

    def test_card_price_is_labelled_and_price_for_unit_not_entire_package(self):
        result=analyze({'subject':'쌀 10kg (카드 25,900원/무료)'})
        self.assertIn('conditional_price',result['warnings'])
        result=analyze({'subject':'쌀 10kg 100g당 200원'})
        self.assertIsNone(result['price'])
