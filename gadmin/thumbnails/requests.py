"""Durable PostgreSQL requests; notifications only wake the single image worker."""
import select


class Requests:
    def __init__(self):
        import psycopg2
        from django.db import connection
        config = connection.settings_dict
        self.connection = connection
        self.listener = psycopg2.connect(
            dbname=config['NAME'], user=config['USER'], password=config['PASSWORD'],
            host=config['HOST'], port=config.get('PORT') or 5432, connect_timeout=5,
            application_name='geteverything-thumbnail-listener')
        self.listener.autocommit = True
        with self.listener.cursor() as cursor:
            cursor.execute('LISTEN geteverything_thumbnail_requests')

    def drain(self, store, deals, limit=50):
        with self.connection.cursor() as cursor:
            cursor.execute('SELECT deal_id,revision,requested_at FROM public.thumbnail_requests ORDER BY requested_at,deal_id LIMIT %s', [limit])
            events = cursor.fetchall()
        for deal_id, revision, requested_at in events:
            row = deals.lookup(deal_id)
            if row:
                job = deals.reconcile(store, row)
                store.request_live(job, revision, requested_at.timestamp())
            # Commit to the local work ledger before acknowledging. A new revision survives.
            with self.connection.cursor() as cursor:
                cursor.execute('DELETE FROM public.thumbnail_requests WHERE deal_id=%s AND revision=%s', [deal_id, revision])
        return len(events)

    def wait(self, timeout=5):
        if select.select([self.listener], [], [], timeout)[0]:
            self.listener.poll()
            self.listener.notifies.clear()

    def close(self):
        self.listener.close()
