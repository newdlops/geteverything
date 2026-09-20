from django.apps import AppConfig


class TestDealsConfig(AppConfig):
    name = 'gadmin.deals'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        from pgvector.django import HnswIndex
        from gadmin.deals.models import Deal
        # The unrelated PostgreSQL vector search index cannot be created by SQLite.
        Deal._meta.indexes = [index for index in Deal._meta.indexes if not isinstance(index, HnswIndex)]
