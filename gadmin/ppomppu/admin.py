from django.contrib import admin

from ppomppu.models import PpomppuDeal

# Register your models here.

@admin.register(PpomppuDeal)
class PpomppuAdmin(admin.ModelAdmin):
    list_display=['cool_n_joy_id','category', 'subject', 'create_at', 'recommend_count']

# Register your models here.