from django.core.exceptions import FieldDoesNotExist
from django.http import StreamingHttpResponse
from django.contrib import admin
import xlsx_streaming
import itertools
from gadmin.deals.models import Deal, DealClassification
from django.utils.html import format_html
from .export_filelds_action_form import ExportFieldsActionForm
from django_admin_action_forms import AdminActionFormsMixin, action_with_form
from gadmin.metrics import admin as measurements_admin
from gadmin.products import admin as products_admin

# Register your models here.


@admin.register(Deal)
class DealAdmin(AdminActionFormsMixin, admin.ModelAdmin):
    list_display=[
        'community_name',
        'category',
        'standard_category',
        'subject',
        'write_at',
        'create_at',
        'recommend_count',
        'view_count',
        'origin_url',
        'shop_url_1',
        'article_id', #
        'shop_name',
        'thumbnail',
        'price',
        'currency',
        'delivery_price',
        'dislike_count',
        'update_at',
        'crawled_at',
        'is_end'
    ]
    list_display_links = ['subject']
    list_filter = ['community_name', 'category']
    list_select_related = ['classification']

    @admin.display(description='표준 카테고리')
    def standard_category(self, obj):
        result = getattr(obj, 'classification', None)
        return result.get_category_display() if result and result.category else '미분류'

    @action_with_form(
        ExportFieldsActionForm,
        description="Stream XLSX Download"
    )
    def action_stream_xlsx(self, request, queryset, form):
        """
        쿼리셋을 xlsx_streaming으로 스트림 생성 후 StreamingHttpResponse로 반환
        """
        # values_list에 내보낼 컬럼 지정

        model = self.model
        selected = form['fields_to_export']
        header_labels = []
        for field_name in selected:
            try:
                field = model._meta.get_field(field_name)
                label = str(field.verbose_name)
            except FieldDoesNotExist:
                # list_display에 정의된 admin 메서드나 속성일 때
                attr = getattr(self, field_name, None)
                label = getattr(attr, 'short_description', None) \
                        or field_name.replace('_', ' ').capitalize()
            header_labels.append(label)


        header = tuple(header_labels)
        data_iter = itertools.chain(
            [header],
            queryset.values_list(*selected).iterator(chunk_size=100)
        )

        stream = xlsx_streaming.stream_queryset_as_xlsx(
            data_iter,
            batch_size=100
        )
        response = StreamingHttpResponse(
            stream,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = 'attachment; filename="deal_export.xlsx"'
        return response

    # action_stream_xlsx.short_description = "Stream XLSX Download"
    # action_form = ExportFieldsActionForm
    actions = ['action_stream_xlsx']

    def origin_url(self, obj):
        return format_html('<a href="{}" target="_blank" rel="noopener noreferrer">{}</a>', obj.origin_url, obj.origin_url)
    origin_url.short_description = '원글 링크'

    def shop_url_1(self, obj):
        return format_html('<a href="{}" target="_blank" rel="noopener noreferrer">{}</a>', obj.shop_url_1, obj.shop_url_1)
    shop_url_1.short_description = '쇼핑몰 링크'


class StandardCategoryFilter(admin.SimpleListFilter):
    title = '표준 대분류'
    parameter_name = 'standard_root'

    def lookups(self, request, model_admin):
        from gadmin.categories.taxonomy import GROUPS
        return [('unclassified', '미분류'), *((code, label) for code, (label, _) in GROUPS.items())]

    def queryset(self, request, queryset):
        from django.db.models import Q
        from gadmin.categories.taxonomy import GROUPS
        value = self.value()
        if value == 'unclassified':
            return queryset.filter(category='')
        if value in GROUPS:
            return queryset.filter(Q(category=value) | Q(category__startswith=value + '.'))
        return queryset


@admin.register(DealClassification)
class DealClassificationAdmin(admin.ModelAdmin):
    list_display = ['input_title', 'category', 'status', 'source', 'manual_override', 'classified_at']
    list_display_links = ['input_title']
    list_filter = ['status', 'source', 'manual_override', StandardCategoryFilter, 'deal__community_name']
    search_fields = ['input_title']
    list_per_page = 30
    ordering = ['-requested_at']
    list_select_related = ['deal']
    fields = ['input_title', 'original_category', 'category', 'candidate', 'status', 'source', 'manual_override', 'reason_summary', 'measurements_link', 'last_error', 'classified_at', 'classifier_version']
    readonly_fields = ['input_title', 'original_category', 'candidate', 'status', 'source', 'manual_override', 'reason_summary', 'measurements_link', 'last_error', 'classified_at', 'classifier_version']
    actions = ['retry_automatically']

    class Media:
        css = {'all': ['monitoring/categories.css']}

    def formfield_for_choice_field(self, db_field, request, **kwargs):
        field = super().formfield_for_choice_field(db_field, request, **kwargs)
        if db_field.name == 'category':
            field.help_text = '저장한 분류는 자동 작업이 변경하지 않습니다. 자동 분류를 다시 사용하려면 목록에서 해당 글을 선택하고 “자동 분류로 되돌리고 다시 처리”를 실행하세요.'
        return field

    @admin.display(description='커뮤니티 원본 분류')
    def original_category(self, obj):
        return obj.deal.category or '없음'

    @admin.display(description='분류 근거')
    def reason_summary(self, obj):
        reasons={'no_clear_product':'등록된 상품어휘와 일치하지 않음','conflicting_products':'서로 다른 상품군의 표현이 함께 등장함',
            'promotion_only':'상품명 없이 할인 행사만 안내함','unavailable_title':'분류할 제목을 확인할 수 없음','operator_override':'관리자 수동 지정'}
        prefixes = {'product':'상품 표현', 'main_product':'주 상품과 구성품',
                    'source_category':'원본 게시판 분류', 'shop_host':'판매처 도메인',
                    'shop_name':'판매처', 'benefit':'혜택 안내',
                    'source_food_quantity':'식품·건강 게시판과 식품 수량 표현',
                    'source_dosage':'식품·건강 게시판과 복용량 표현',
                    'source_promotion':'행사 게시판과 할인 안내'}
        kind, _, detail = obj.reason.partition(':')
        if kind in prefixes:
            return f'{prefixes[kind]} · {detail}'
        return reasons.get(obj.reason,obj.reason)

    @admin.display(description='수량·단가')
    def measurements_link(self, obj):
        from django.urls import reverse
        measurement=getattr(obj.deal,'measurements',None)
        if not measurement:
            return '수치 분석 대기'
        return format_html('<a href="{}">{} · 수량·단가 상세 보기</a>',
            reverse('admin:deals_dealmeasurements_change',args=[obj.pk]),measurements_admin.quantity_summary(measurement.result))

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        from django.db import transaction
        from django.utils import timezone
        from gadmin.categories.rules import title_hash
        # A save is a deliberate manual decision, even when the selected value is unchanged.
        with transaction.atomic():
            current = DealClassification.objects.select_for_update().get(pk=obj.pk)
            current.category = obj.category
            current.candidate = ''
            current.status = 'ready' if obj.category else 'review'
            current.source = 'manual'
            current.manual_override = True
            current.request_revision += 1
            current.lease_until = None
            current.last_error = ''
            current.title_hash = title_hash(current.input_title)
            current.reason = 'operator_override'
            current.classifier_version = 'manual'
            current.classified_at = timezone.now()
            current.save()

    @admin.action(description='선택한 글을 자동 분류로 되돌리고 다시 처리', permissions=['change'])
    def retry_automatically(self, request, queryset):
        from django.db import transaction
        from django.utils import timezone
        ids = list(queryset.values_list('deal_id', flat=True)[:201])
        if len(ids) > 200:
            self.message_user(request, '한 번에 200건 이하로 선택해 주세요.', level='error')
            return
        if not ids:
            return
        with transaction.atomic():
            rows = list(DealClassification.objects.filter(pk__in=ids).select_for_update().prefetch_related('deal').order_by('deal_id'))
            for row in rows:
                row.category = row.candidate = row.source = row.last_error = row.reason = ''
                row.status = 'pending'
                row.manual_override = False
                row.input_title = row.deal.subject or ''
                row.request_revision += 1
                row.lease_until = row.classified_at = None
                row.attempts = row.priority = 0
                row.requested_at = row.next_attempt_at = timezone.now()
            DealClassification.objects.bulk_update(rows, ['category', 'candidate', 'source', 'last_error', 'reason', 'status', 'manual_override', 'input_title', 'request_revision', 'lease_until', 'classified_at', 'attempts', 'priority', 'requested_at', 'next_attempt_at'])
        self.message_user(request, f'{len(ids)}건을 자동 분류 대기열에 등록했습니다.')
