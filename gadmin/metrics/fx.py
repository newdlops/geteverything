"""ECB public reference data, cached in the DB; never an inference API."""
import copy
from functools import lru_cache
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import re
import urllib.request
import urllib.parse
import time

from defusedxml import ElementTree
from .money import string

SOURCE = 'https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml'
LATEST_KEY = 'fx:ECB:latest'


def parse_rates(payload, today=None):
    today = today or datetime.now(timezone.utc).date()
    if len(payload) > 65536:
        raise ValueError('oversized_fx_document')
    root = ElementTree.fromstring(payload)
    days = [element for element in root.iter() if 'time' in element.attrib]
    if len(days)!=1:
        raise ValueError('invalid_fx_date')
    day = date.fromisoformat(days[0].attrib['time'])
    if day > today or (today-day).days > 7:
        raise ValueError('stale_or_future_fx_date')
    rates = {'EUR':Decimal(1)}
    for element in days[0]:
        code = element.attrib.get('currency','')
        if not re.fullmatch('[A-Z]{3}',code) or code in rates:
            raise ValueError('invalid_fx_currency')
        rate = Decimal(element.attrib['rate'])
        if not rate.is_finite() or not Decimal('0.000001') < rate < Decimal('1000000000'):
            raise ValueError('invalid_fx_rate')
        rates[code] = rate
    if not {'KRW','USD','JPY'} <= rates.keys():
        raise ValueError('incomplete_fx_document')
    return {'provider':'ECB','source':SOURCE,'date':day.isoformat(),'fetched_at':datetime.now(timezone.utc).isoformat(),
            'krw_per_unit':{code:string((rates['KRW']/rate).quantize(Decimal('0.000000000001'))) for code,rate in rates.items()}}


def refresh():
    """One bounded request. Keep the last successful snapshot if this raises."""
    from django.db import close_old_connections, transaction
    from gadmin.deals.models import ClassificationState
    close_old_connections()
    try:
        request = urllib.request.Request(SOURCE,headers={'User-Agent':'GetEverything-price-reference/1.0'})
        with urllib.request.urlopen(request,timeout=8) as response:
            if urllib.parse.urlsplit(response.url).hostname != 'www.ecb.europa.eu':
                raise ValueError('unexpected_fx_host')
            snapshot = parse_rates(response.read(65537))
        with transaction.atomic():
            latest,_ = ClassificationState.objects.select_for_update().get_or_create(key=LATEST_KEY,defaults={'value':{}})
            if latest.value.get('date','') > snapshot['date']:
                raise ValueError('older_fx_document')
            ClassificationState.objects.update_or_create(key='fx:ECB:'+snapshot['date'],defaults={'value':snapshot})
            latest.value = snapshot
            latest.save(update_fields=['value'])
        return snapshot['date']
    finally:
        close_old_connections()


def latest():
    from gadmin.deals.models import ClassificationState
    return ClassificationState.objects.filter(key=LATEST_KEY).values_list('value',flat=True).first()


@lru_cache(maxsize=2)
def _latest_at(bucket):
    return latest()


def cached_latest():
    return _latest_at(int(time.time()//300))


def convert(result, snapshot=None, today=None):
    result = copy.deepcopy(result)
    price = result.get('price')
    result['fx'] = None
    result['price_krw'] = result['total_price_with_shipping_krw'] = None
    if not price or not price.get('currency'):
        return result
    code = price['currency']
    rate = Decimal(1) if code=='KRW' else None
    if code!='KRW':
        if not snapshot or code not in snapshot.get('krw_per_unit',{}):
            result['warnings'].append('fx_missing')
            return result
        today = today or datetime.now(timezone.utc).date()
        age = (today-date.fromisoformat(snapshot['date'])).days
        result['fx'] = {key:snapshot[key] for key in ('provider','source','date','fetched_at')}
        result['fx'].update(krw_per_unit=snapshot['krw_per_unit'][code],comparison_only=True,stale=age>7 or age<0)
        if result['fx']['stale']:
            result['warnings'].append('fx_stale')
            return result
        rate = Decimal(snapshot['krw_per_unit'][code])
    def won(amount):
        return string((Decimal(amount)*rate).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP))
    result['price_krw'] = won(price['amount'])
    if result.get('total_price_with_shipping') is not None:
        result['total_price_with_shipping_krw'] = won(result['total_price_with_shipping'])
    for row in result.get('unit_prices',[]):
        # Convert the unrounded full price before division to avoid double rounding.
        ratio = Decimal(row['basis_amount']) / Decimal(row['quantity_total'])
        row['amount_krw'] = won(Decimal(price['amount'])*ratio)
        row['amount_with_shipping_krw'] = won(Decimal(result['total_price_with_shipping'])*ratio) if result.get('total_price_with_shipping') is not None else None
    return result
