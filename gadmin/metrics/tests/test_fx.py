from datetime import date
import unittest
from gadmin.metrics.fx import parse_rates, convert
from gadmin.metrics.parser import analyze

XML = b'''<Envelope><Cube><Cube time="2026-09-17"><Cube currency="USD" rate="1.2"/><Cube currency="KRW" rate="1600"/><Cube currency="JPY" rate="180"/></Cube></Cube></Envelope>'''


class FxTests(unittest.TestCase):
    def test_cross_rates_are_per_one_currency_unit(self):
        rates=parse_rates(XML,date(2026,9,18))
        self.assertEqual(rates['krw_per_unit']['KRW'],'1')
        result=convert(analyze({'subject':'음료 500ml 24개','numeric_evidence':{'price':'USD 19.99'}}),rates,date(2026,9,18))
        self.assertEqual(result['price_krw'],'26653.33')
        self.assertEqual(result['unit_prices'][1]['amount_krw'],'1110.56')
        yen=convert(analyze({'subject':'상품','numeric_evidence':{'price':'JPY 100'}}),rates,date(2026,9,18))
        self.assertEqual(yen['price_krw'],'888.89')

    def test_stale_missing_and_unsupported_rates_never_synthesize_won(self):
        result=analyze({'subject':'상품','numeric_evidence':{'price':'USD 10'}})
        self.assertIsNone(convert(result,None)['price_krw'])
        rates=parse_rates(XML,date(2026,9,18))
        self.assertIsNone(convert(result,rates,date(2026,9,25))['price_krw'])
        self.assertIn('fx_stale',convert(result,rates,date(2026,9,25))['warnings'])

    def test_invalid_rate_documents_are_rejected(self):
        for payload in [XML.replace(b'1.2',b'NaN'),XML.replace(b'1.2',b'0'),XML.replace(b'1.2',b'-1'),XML.replace(b'2026-09-17',b'2026-09-20'),XML.replace(b'KRW',b'BAD')]:
            with self.subTest(payload=payload),self.assertRaises(ValueError):
                parse_rates(payload,date(2026,9,18))
