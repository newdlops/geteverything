from django.contrib import admin

from gadmin.coolnjoy.models import CoolNJoyDeal


# Register your models here.

@admin.register(CoolNJoyDeal)
class CoolNJoyAdmin(admin.ModelAdmin):
    list_display=['cool_n_joy_id','category', 'subject', 'create_at', 'recommend_count']

