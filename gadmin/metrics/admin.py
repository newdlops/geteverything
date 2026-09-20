"""Native Django admin for readable arithmetic and its evidence."""
from decimal import Decimal
from django.contrib import admin
from django.utils.html import format_html, format_html_join
from gadmin.deals.models import DealMeasurements
from .fx import cached_latest, convert
from .parser import WARNING_LABELS


def amount(value):
    return f'{Decimal(value):,}' if value is not None else '미확인'


def current(obj):
    if not hasattr(obj,'_converted_measurements'):
        code = (obj.result.get('price') or {}).get('currency')
        obj._converted_measurements = convert(obj.result,cached_latest() if code and code!='KRW' else None)
    return obj._converted_measurements


def quantity_summary(data):
    items = []
    for key, unit in [('weight_g','g'),('volume_ml','ml')]:
        if data.get(key):
            items.append(f"총 {amount(data[key]['total'])}{unit}")
    if data.get('quantity'):
        items.append(f"{amount(data['quantity']['count'])}{data['quantity']['unit']}")
    if data.get('capacity_ml'):
        capacity=data['capacity_ml']
        items.append(f"표시 용량 {amount(capacity['per_item'] or capacity['total'])}ml")
    return ' · '.join(items) or '총량 미확인'


class CurrencyFilter(admin.SimpleListFilter):
    title = '가격 통화'
    parameter_name = 'price_currency'

    def lookups(self, request, model_admin):
        return [('KRW','원화'),('USD','미국 달러'),('JPY','일본 엔'),('EUR','유로'),('CNY','중국 위안')]

    def queryset(self, request, queryset):
        if self.value() in ('KRW','USD','JPY','EUR','CNY'):
            return queryset.filter(result__price__currency=self.value())
        return queryset


@admin.register(DealMeasurements)
class MeasurementsAdmin(admin.ModelAdmin):
    list_display = ['title','status','quantities','unit_prices','processed_at']
    list_display_links = ['title']
    list_filter = ['status',CurrencyFilter,'deal__community_name']
    list_select_related = ['deal']
    search_fields = ['deal__subject']
    ordering = ['-requested_at']
    list_per_page = 30
    fields = ['title','status','quantities','quantity_evidence','prices','unit_prices','exchange_rate','notes','collected_evidence','processed_at','parser_version','last_error']
    readonly_fields = fields

    class Media:
        css = {'all':['monitoring/categories.css']}

    def has_add_permission(self, request): return False
    def has_delete_permission(self, request, obj=None): return False
    def has_change_permission(self, request, obj=None): return False

    @admin.display(description='상품 제목')
    def title(self, obj):
        return obj.input.get('subject') or obj.deal.subject or '제목 없음'

    @admin.display(description='총량·수량')
    def quantities(self, obj):
        return '계산 대기' if obj.status=='pending' else quantity_summary(obj.result)

    @admin.display(description='수량 계산 근거')
    def quantity_evidence(self, obj):
        rows = [(obj.result[key]['evidence'],) for key in ('weight_g','volume_ml','quantity','capacity_ml') if obj.result.get(key)]
        rows += [(f"성분 함량 {item['evidence']} (총중량 제외)",) for item in obj.result.get('strengths',[])]
        return format_html_join('','<div>{}</div>',rows) if rows else '확인 가능한 표기 없음'

    @admin.display(description='상품 금액·배송비')
    def prices(self, obj):
        data = current(obj)
        price, shipping = data.get('price'),data.get('shipping')
        rows = []
        if price:
            rows.append((f"상품 금액: {amount(price['amount'])} {price['currency'] or '(통화 미확인)'}",))
            if price['currency']!='KRW' and data.get('price_krw') is not None:
                rows.append((f"비교용 원화 금액: {amount(data['price_krw'])}원",))
        if shipping:
            rows.append((f"배송비: {amount(shipping['amount'])} {shipping['currency'] or '(통화 미확인)'}",))
        else:
            rows.append(('배송비: 미확인',))
        if data.get('total_price_with_shipping') is not None:
            rows.append((f"배송비 포함: {amount(data['total_price_with_shipping'])} {price['currency']}",))
        return format_html_join('','<div>{}</div>',rows)

    @admin.display(description='단위당 가격')
    def unit_prices(self, obj):
        data = current(obj)
        rows=[]
        for row in data.get('unit_prices',[]):
            label=f"{row['basis_amount']}{row['basis_unit']}당 {amount(row['amount'])} {row['currency']}"
            if row.get('amount_krw') is not None and row['currency']!='KRW':
                label+=f" (약 {amount(row['amount_krw'])}원)"
            rows.append((label,))
            if row.get('amount_with_shipping') is not None:
                rows.append((f"배송비 포함 {amount(row['amount_with_shipping'])} {row['currency']}",))
        return format_html_join('','<div>{}</div>',rows) if rows else '계산 가능한 가격·총량 없음'

    @admin.display(description='적용 환율')
    def exchange_rate(self, obj):
        data=current(obj)
        fx=data.get('fx')
        if not fx:
            return '원화 상품' if (data.get('price') or {}).get('currency')=='KRW' else '사용 가능한 환율 없음'
        code=data['price']['currency']
        return format_html('{} 기준 · ECB · 1 {} = {}원<br>{}<br>상품 비교용이며 카드 수수료·관세는 포함하지 않습니다.',
            fx['date'],code,amount(fx['krw_per_unit']),'기준일이 오래되어 환산 중지' if fx['stale'] else '공식 일별 기준환율')

    @admin.display(description='계산 시 확인 사항')
    def notes(self, obj):
        codes=current(obj).get('warnings',[])
        return format_html_join('','<div>{}</div>',[(WARNING_LABELS.get(code,code),) for code in codes]) if codes else '없음'

    @admin.display(description='수집한 가격 원문')
    def collected_evidence(self, obj):
        evidence=obj.input.get('numeric_evidence') or {}
        rows=[('상품 가격',evidence.get('price') or '원문 없음'),('배송비',evidence.get('delivery') or '원문 없음')]
        price=obj.result.get('price')
        if price:
            rows.append(('계산에 사용한 표기',price.get('evidence','')))
        return format_html_join('','<div>{}: {}</div>',rows)
