"""A resource-limited image worker woken by crawler database commits."""
import argparse
import json
import os
import signal
import sqlite3
import time

from .discovery import discover_images, discover_post_images, encode_thumbnail
from .fetch import ThumbnailError, fetch, html_text, normalize_url, product_url
from .store import Store


FIELDS = ('id', 'subject', 'origin_url', 'shop_url_1', 'shop_url_2', 'thumbnail')


class Deals:
    def __init__(self):
        from gadmin.deals.models import Deal
        self.model = Deal

    def lookup(self, deal_id):
        return self.model.objects.filter(pk=deal_id).values(*FIELDS).first()

    def discover(self, store):
        cursor = store.meta('last_id')
        if cursor is None:
            rows = list(self.model.objects.order_by('-id').values(*FIELDS)[:500])
        else:
            rows = list(self.model.objects.filter(id__gt=cursor).order_by('id').values(*FIELDS)[:500])
        for row in rows:
            self.reconcile(store, row)
        if rows:
            store.set_meta('last_id', max(row['id'] for row in rows))
        # Observe changed product links and restore a stored URL after older crawler deployments.
        for row in self.model.objects.order_by('-update_at').values(*FIELDS)[:300]:
            self.reconcile(store, row)

    def start_backfill(self, store):
        state = store.meta('backfill')
        if state:
            return state
        maximum = self.model.objects.order_by('-id').values_list('id', flat=True).first() or 0
        state = {'id': str(time.time_ns()), 'phase': 'missing', 'ceiling': maximum,
                 'cursor': maximum + 1, 'scanned': 0, 'started_at': store.now()}
        store.set_meta('backfill', state)
        return state

    def backfill_rows(self, state, limit):
        from django.db.models import Q
        query = self.model.objects.filter(id__lt=state['cursor'], id__lte=state['ceiling'])
        if state['phase'] == 'missing':
            query = query.filter(Q(thumbnail__isnull=True) | Q(thumbnail='') |
                                 ~Q(thumbnail__regex=r'^(https?:)?//[^/\s]+'))
        return list(query.order_by('-id').values(*FIELDS)[:limit])

    def backfill(self, store, limit=50):
        state = store.meta('backfill')
        if not state or state['phase'] not in ('missing', 'all'):
            return
        waiting = store.db.execute("SELECT count(*) FROM jobs WHERE backfill_run=? AND status='pending' AND attempts=0", (state['id'],)).fetchone()[0]
        if waiting >= 50:
            return
        rows = self.backfill_rows(state, min(limit, 50 - waiting))
        for row in rows:
            job = self.reconcile(store, row)
            store.queue_backfill(job, state['id'])
        if rows:
            state['cursor'] = rows[-1]['id']
            state['scanned'] += len(rows)
        elif state['phase'] == 'missing':
            state.update(phase='all', cursor=state['ceiling'] + 1)
        else:
            state.update(phase='draining', scan_finished_at=store.now())
        store.set_meta('backfill', state)

    def reconcile(self, store, row):
        previous = store.get(row['id'])
        job = store.enqueue(row)
        if previous and previous['signature'] != job['signature'] and previous['object_key']:
            self.clear(previous, store.url(previous))
            store.db.execute("UPDATE jobs SET object_key='',expires_at=0,size=0,published=0 WHERE deal_id=?", (job['deal_id'],))
            store.db.commit()
            job = store.get(job['deal_id'])
        job = store.repair_missing(job)
        if store.has_asset(job) and row['thumbnail'] != store.url(job):
            if self.publish(job, store.url(job)):
                store.mark_published(job)
        return job

    def publish(self, job, url):
        from django.db.models import Q
        query = self.model.objects.filter(pk=job['deal_id'])
        for field in ('shop_url_1', 'shop_url_2'):
            value = job['payload'].get(field)
            condition = Q(**{field: value}) if value else (Q(**{field: ''}) | Q(**{field + '__isnull': True}))
            query = query.filter(condition)
        return query.update(thumbnail=url)

    def clear(self, job, url):
        self.model.objects.filter(pk=job['deal_id'], thumbnail=url).update(thumbnail='')


def collect(job, store, *, downloader=fetch):
    payload = job['payload']
    deadline = time.monotonic() + 22
    candidates = []
    reason = 'no_product_image'
    referers = {}
    for key in ('shop_url_1', 'shop_url_2'):
        url = product_url(payload.get(key))
        if not url or url in referers:
            continue
        referers[url] = url
        try:
            page = downloader(url, limit=2*1024*1024, deadline=deadline)
            if 'html' in page.content_type.lower() or page.body.lstrip().startswith((b'<', b'<!')):
                found = discover_images(html_text(page), page.url, payload.get('subject') or '')
                candidates.extend(found)
                referers.update({candidate.url: page.url for candidate in found})
            elif page.content_type.lower().startswith('image/'):
                data, dimensions = encode_thumbnail(page.body)
                return store.save_image(job, data, dimensions, 'product_image_link')
        except ThumbnailError as exc:
            reason = str(exc)
    seen = set()
    for candidate in sorted(candidates, key=lambda value: -value.score)[:3]:
        if candidate.url in seen:
            continue
        seen.add(candidate.url)
        try:
            image = downloader(candidate.url, limit=4*1024*1024, deadline=deadline,
                               referer=referers[candidate.url])
            data, dimensions = encode_thumbnail(image.body)
            return store.save_image(job, data, dimensions, candidate.evidence)
        except ThumbnailError as exc:
            reason = str(exc)
    # Preserve an already stored fallback's original expiry while retrying the product page.
    if store.has_asset(job) and job['evidence'] != 'community_body':
        store.fail(job, reason)
        return store.get(job['deal_id'])
    fallback = normalize_url(payload.get('fallback'), payload.get('origin_url') or '')
    if fallback and not fallback.startswith(store.base_url):
        try:
            image = downloader(fallback, limit=4*1024*1024, deadline=time.monotonic()+8,
                               referer=payload.get('origin_url') or '')
            data, dimensions = encode_thumbnail(image.body, fallback=True)
            return store.save_image(job, data, dimensions, 'community_fallback')
        except ThumbnailError as exc:
            reason = str(exc)
    origin = normalize_url(payload.get('origin_url'))
    if origin:
        try:
            deadline = time.monotonic() + 12
            page = downloader(origin, limit=2*1024*1024, deadline=deadline)
            for candidate in discover_post_images(html_text(page), page.url, payload.get('subject') or '')[:3]:
                try:
                    image = downloader(candidate.url, limit=4*1024*1024, deadline=deadline,
                                       referer=page.url)
                    data, dimensions = encode_thumbnail(image.body, fallback=True)
                    return store.save_image(job, data, dimensions, candidate.evidence)
                except ThumbnailError as exc:
                    reason = str(exc)
        except ThumbnailError as exc:
            reason = str(exc)
    store.fail(job, reason)
    return store.get(job['deal_id'])


def process_job(job, store, deals):
    started_at = store.now()
    try:
        result = collect(job, store)
    except (MemoryError, sqlite3.Error, OSError):
        raise
    except Exception as exc:
        # Malformed third-party data must not poison every later batch.
        store.fail(job, 'unexpected_' + type(exc).__name__)
        result = store.get(job['deal_id'])
    if store.has_asset(result) and deals.publish(result, store.url(result)):
        store.mark_published(result)
    store.set_meta('last_job', {'deal_id': job['deal_id'], 'started_at': started_at,
                              'finished_at': store.now(), 'status': result['status'],
                              'error': result['error'], 'evidence': result['evidence'],
                              'requested_at': job['live_requested_at'], 'revision': job['live_revision']})
    return result


def run(store, deals, *, budget=55, batch=12, requests=None, maintenance=True, should_stop=lambda: False):
    start = time.monotonic()
    store.review_community_images()
    stats = {'expired': 0, 'collected': 0, 'fallback': 0, 'failed': 0, 'requests': 0}
    if maintenance:
        stats['expired'] = store.expire(deals.clear)
        store.clean_orphans()
        deals.discover(store)
        deals.backfill(store)
    unpublished = store.db.execute("SELECT deal_id FROM jobs WHERE published=0 AND object_key<>'' AND expires_at>? LIMIT 100", (store.now(),)).fetchall()
    for row in unpublished:
        job = store.repair_missing(store.get(row[0]))
        if store.has_asset(job) and deals.publish(job, store.url(job)):
            store.mark_published(job)
    for _ in range(batch):
        if should_stop() or time.monotonic() - start >= budget:
            break
        if requests:
            stats['requests'] += requests.drain(store, deals)
        due = store.due(1)
        if not due:
            break
        result = process_job(due[0], store, deals)
        stats[{'ready': 'collected', 'fallback': 'fallback', 'failed': 'failed'}[result['status']]] += 1
    stats['seconds'] = round(time.monotonic() - start, 2)
    stats['pending'] = store.db.execute("SELECT count(*) FROM jobs WHERE status IN ('pending','failed','fallback') AND attempts<3").fetchone()[0]
    stats['backfill'] = store.backfill_status()
    store.set_meta('last_run', {'at': time.time(), **stats})
    return stats


def watch(store, deals, *, batch=12, budget=55):
    from .requests import Requests
    stopping = False
    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    requests = Requests()
    maintenance_at = 0
    try:
        while not stopping:
            now = time.monotonic()
            maintenance = now >= maintenance_at
            if maintenance:
                maintenance_at = now + 60
            stats = run(store, deals, batch=batch, budget=budget, requests=requests,
                        maintenance=maintenance, should_stop=lambda: stopping)
            if maintenance or any(stats[key] for key in ('collected','fallback','failed','requests')):
                print(json.dumps(stats), flush=True)
            if not stopping:
                requests.wait(0 if store.due(1, live_only=True) else 5)
    finally:
        requests.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch', type=int, default=12)
    parser.add_argument('--budget', type=int, default=55)
    parser.add_argument('--start-backfill', action='store_true', help='Start or resume one durable historical pass')
    parser.add_argument('--status', action='store_true', help='Print backfill progress without downloading')
    parser.add_argument('--watch', action='store_true', help='Listen for crawl commits and process them before historical work')
    args = parser.parse_args()
    if not 1 <= args.batch <= 50 or not 1 <= args.budget <= 90:
        raise ValueError('Invalid worker bounds')
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gadmin.admin.settings')
    import django
    django.setup()
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute("SET statement_timeout = '5s'")
        cursor.execute("SET lock_timeout = '1s'")
    store = Store(os.environ.get('THUMBNAIL_ROOT', '/var/lib/geteverything-thumbnails'),
                  os.environ['THUMBNAIL_PUBLIC_BASE_URL'],
                  ttl_days=int(os.environ.get('THUMBNAIL_TTL_DAYS', '90')))
    try:
        deals = Deals()
        if args.start_backfill:
            deals.start_backfill(store)
        if args.watch:
            watch(store, deals, batch=args.batch, budget=args.budget)
            return
        result = store.backfill_status() if args.status else run(store, deals, batch=args.batch, budget=args.budget)
        print(json.dumps(result))
    finally:
        store.db.close()
        connection.close()


if __name__ == '__main__':
    main()
