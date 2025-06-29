from django.http import StreamingHttpResponse
from django.contrib import admin
import xlsx_streaming
from deals.models import Deal
from django.utils.html import format_html
from .export_filelds_action_form import ExportFieldsActionForm
from django_admin_action_forms import AdminActionFormsMixin, action_with_form

# Register your models here.


@admin.register(Deal)
class DealAdmin(AdminActionFormsMixin, admin.ModelAdmin):
    list_display=[
        'community_name',
        'category',
        'subject',
        'write_at',
        'create_at',
        'recommend_count',
        'view_count',
        'origin_link',
        'shop_url',
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

    @action_with_form(
        ExportFieldsActionForm,
        description="Stream XLSX Download"
    )
    def action_stream_xlsx(self, request, queryset, form):
        """
        쿼리셋을 xlsx_streaming으로 스트림 생성 후 StreamingHttpResponse로 반환
        """
        # values_list에 내보낼 컬럼 지정
        qs_values = queryset.values_list('community_name', 'category', 'subject', 'write_at', 'create_at', 'recommend_count', 'view_count')
        stream = xlsx_streaming.stream_queryset_as_xlsx(
            qs_values,
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

    def origin_link(self, obj):
        return format_html('<a href="{}" target="_blank" rel="noopener noreferrer">{}</a>', obj.origin_url, obj.origin_url)
    origin_link.short_description = '원글 링크'

    def shop_url(self, obj):
        return format_html('<a href="{}" target="_blank" rel="noopener noreferrer">{}</a>', obj.shop_url_1, obj.shop_url_1)
    shop_url.short_description = '쇼핑몰 링크'
