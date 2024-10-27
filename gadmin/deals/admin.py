from django.contrib import admin

from deals.models import Deal

# Register your models here.

@admin.register(Deal)
class DealAdmin(admin.ModelAdmin):
    list_display=['category', 'subject', 'create_at', 'recommend_count']

