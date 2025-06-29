from django.contrib import admin

from deals.models import Deal
from django.utils.html import format_html

# Register your models here.

@admin.register(Deal)
class DealAdmin(admin.ModelAdmin):
    list_display=['community_name', 'category', 'subject', 'write_at', 'create_at', 'recommend_count', 'view_count', 'origin_link', 'shop_url']
    list_display_links = ['subject']
    list_filter = ['community_name', 'category']

    def origin_link(self, obj):
        return format_html('<a href="{}" target="_blank" rel="noopener noreferrer">{}</a>', obj.origin_url, obj.origin_url)
    origin_link.short_description = '원글 링크'

    def shop_url(self, obj):
        return format_html('<a href="{}" target="_blank" rel="noopener noreferrer">{}</a>', obj.shop_url_1, obj.shop_url_1)
    shop_url.short_description = '쇼핑몰 링크'
