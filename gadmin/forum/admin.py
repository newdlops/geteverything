from django.contrib import admin
from .models.post import Post, Comment
from django_summernote.admin import SummernoteModelAdmin


# Register your models here.

@admin.register(Post)
class PostAdmin(SummernoteModelAdmin):
    list_display = [field.name for field in Post._meta.fields]
    list_filter = [field.name for field in Post._meta.fields]
    summernote_fields = 'content'

@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = [field.name for field in Comment._meta.fields]
    list_filter = [field.name for field in Comment._meta.fields]
