from django_summernote.apps import DjangoSummernoteConfig


class DjangoSummernotePinnedAutoFieldConfig(DjangoSummernoteConfig):
    name = "django_summernote"
    default_auto_field = "django.db.models.AutoField"
