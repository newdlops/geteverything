from django.contrib import admin

from deals.models import Deal

# Register your models here.

@admin.register(Deal)
class DealAdmin(admin.ModelAdmin):
    list_display=['community_name', 'category', 'subject', 'create_at', 'recommend_count', 'view_count']
    list_display_links = ['subject']
