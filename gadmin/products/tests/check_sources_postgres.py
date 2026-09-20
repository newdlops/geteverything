"""Exercise the production SQL dialect inside an isolated, rolled-back schema."""
import importlib
import json
import uuid
from unittest.mock import Mock, patch


def verify():
    import django
    django.setup()
    from django.db import connection, transaction
    from django.utils import timezone
    from gadmin.deals.models import (ClassificationState, Deal, DealClassification, DealProduct,
                                     Product, ProductPrice, ProductReference, ProductSource)
    from gadmin.products import identity, jobs, sources
    from gadmin.thumbnails.fetch import Download
    assert connection.vendor == 'postgresql'
    schema = 'check_product_sources_' + uuid.uuid4().hex[:12]
    models = [Deal, ClassificationState, DealClassification, Product, DealProduct,
              ProductPrice, ProductSource, ProductReference]
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute('CREATE SCHEMA ' + connection.ops.quote_name(schema))
            cursor.execute('SET LOCAL search_path TO ' + connection.ops.quote_name(schema) + ',public')
        with connection.schema_editor() as editor:
            for model in models:
                editor.create_model(model)
        trigger = importlib.import_module('gadmin.deals.migrations.0015_product_sources').SOURCE_TRIGGER.sql
        with connection.cursor() as cursor:
            cursor.execute(trigger.replace('public', schema))
        url = 'https://smartstore.naver.com/logitech/products/123'
        a = Deal.objects.create(subject='로지텍 MX Master 4 무선 마우스', shop_url_1=url, price=1000, currency='WON', crawled_at=timezone.now())
        source = ProductSource.objects.get(pk=a.pk)
        assert source.revision == 1 and source.input['urls'] == [url, '']
        Deal.objects.filter(pk=a.pk).update(view_count=50, shop_url_1=url)
        assert ProductSource.objects.get(pk=a.pk).revision == 1
        jobs.seed(a)
        sources.collect_pending()
        data = identity.grounded(a.subject, {'is_product': True, 'brand': '로지텍', 'name': 'MX Master 4',
            'model': 'MX Master 4', 'variant': '', 'category': 'computer'})[0]
        jobs.resolve(DealProduct.objects.get(pk=a.pk), data, 'llm')
        b = Deal.objects.create(subject='로지텍 MX Master 4 블루투스 마우스 2개', shop_url_1=url, price=1800, currency='WON', crawled_at=timezone.now())
        jobs.seed(b)
        sources.collect_pending()
        assignment = DealProduct.objects.get(pk=b.pk)
        assert assignment.source == 'identifier'
        assert assignment.product_id == DealProduct.objects.get(pk=a.pk).product_id
        assert ProductPrice.objects.count() == 2
        old = ProductSource.objects.get(pk=b.pk)
        new_url = 'https://item.gmarket.co.kr/Item?goodscode=987'
        Deal.objects.filter(pk=b.pk).update(shop_url_1=new_url)
        new = ProductSource.objects.get(pk=b.pk)
        assert new.revision == 2 and new.status == 'pending' and new.priority == 0
        assert not sources.persist(old, sources.references(old.input))
        assert sources.match(assignment) is None
        sources.collect_pending()
        assert list(ProductReference.objects.filter(source_id=b.pk).values_list('namespace', flat=True)) == ['gmarket']
        Deal.objects.filter(pk=b.pk).update(subject='로지텍 MX Master 3S')
        assert ProductSource.objects.get(pk=b.pk).revision == 3
        assert ProductPrice.objects.count() == 2
        short = Deal.objects.create(subject=a.subject, shop_url_1='https://naver.me/test', crawled_at=timezone.now())
        sources.collect_pending()
        downloader = Mock(return_value=Download(url, b'', ''))
        # Keep this integration check inside its isolated transaction; production calls
        # the resolver on a dedicated thread with its own connection lifecycle.
        with patch('django.db.close_old_connections'):
            sources.resolve_redirects_once(downloader)
        assert ProductSource.objects.get(pk=short.pk).status == 'ready'
        cache = ClassificationState.objects.get(key__startswith='products:redirect:')
        cache.full_clean()
        repeated = Deal.objects.create(subject=a.subject, shop_url_1='https://naver.me/test', crawled_at=timezone.now())
        sources.collect_pending()
        with patch('django.db.close_old_connections'):
            sources.resolve_redirects_once(downloader)
        assert ProductSource.objects.get(pk=repeated.pk).status == 'ready'
        assert downloader.call_count == 1
        with connection.cursor() as cursor:
            cursor.execute('SELECT table_schema FROM information_schema.tables WHERE table_schema=%s', [schema])
            assert len(cursor.fetchall()) == len(models)
        transaction.set_rollback(True)
    with connection.cursor() as cursor:
        cursor.execute('SELECT 1 FROM pg_namespace WHERE nspname=%s', [schema])
        assert cursor.fetchone() is None
    return {'postgres_checks': 'passed', 'schema_rolled_back': True,
            'checks': ['new_post', 'no_change', 'url_change', 'title_change', 'stale_result',
                       'namespaced_lookup', 'shared_product', 'price_preservation', 'redirect_cache_postgres']}


if __name__ == '__main__':
    print(json.dumps(verify()))
