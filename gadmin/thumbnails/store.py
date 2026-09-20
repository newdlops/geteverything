"""A small durable work ledger and atomic files, outside container layers."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import time
from urllib.parse import urlsplit

from .fetch import ThumbnailError, normalize_url, product_url


KEY = re.compile(r"[0-9]{8}/[0-9]{10}-[0-9a-f]{32}\.jpg\Z")
TTL_SECONDS = 90 * 86400


class Store:
    def __init__(self, root, base_url, *, now=time.time, ttl_days=90):
        self.root = Path(root)
        self.objects = self.root / "objects"
        self.objects.mkdir(parents=True, exist_ok=True)
        self.base_url = base_url.rstrip("/") + "/"
        public = urlsplit(self.base_url)
        if (public.scheme not in ('http', 'https') or not public.hostname or public.username
                or public.password or public.query or public.fragment or len(self.base_url)>350):
            raise ValueError("A public thumbnail base URL is required")
        self.now = now
        if not 1 <= ttl_days <= 365:
            raise ValueError('TTL must be between 1 and 365 days')
        self.ttl_seconds = ttl_days * 86400
        self.db = sqlite3.connect(self.root / "queue.sqlite3", timeout=1)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            PRAGMA cache_size=-2048;
            PRAGMA max_page_count=65536;
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs (
                deal_id INTEGER PRIMARY KEY, signature TEXT NOT NULL, payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                next_at REAL NOT NULL DEFAULT 0, object_key TEXT NOT NULL DEFAULT '',
                expires_at REAL NOT NULL DEFAULT 0, evidence TEXT NOT NULL DEFAULT '',
                size INTEGER NOT NULL DEFAULT 0, width INTEGER NOT NULL DEFAULT 0,
                height INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '',
                published INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS jobs_due ON jobs(status,next_at);
            CREATE INDEX IF NOT EXISTS jobs_expiry ON jobs(expires_at);
        ''')
        columns = {row[1] for row in self.db.execute('PRAGMA table_info(jobs)')}
        if 'backfill_run' not in columns:
            self.db.execute("ALTER TABLE jobs ADD COLUMN backfill_run TEXT NOT NULL DEFAULT ''")
        for name, kind in (('live_requested_at', 'REAL'), ('live_revision', 'INTEGER')):
            if name not in columns:
                self.db.execute(f'ALTER TABLE jobs ADD COLUMN {name} {kind} NOT NULL DEFAULT 0')
        self.db.execute('CREATE INDEX IF NOT EXISTS jobs_backfill ON jobs(backfill_run,status,attempts)')
        self.db.commit()

    def meta(self, key, default=None):
        row = self.db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_meta(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', (key, json.dumps(value)))
        self.db.commit()

    def get(self, deal_id):
        row = self.db.execute('SELECT * FROM jobs WHERE deal_id=?', (deal_id,)).fetchone()
        if row:
            job = dict(row)
            job['payload'] = json.loads(job['payload'])
            return job

    def enqueue(self, row):
        previous = self.get(row['id'])
        original = row.get('thumbnail') or ''
        if original.startswith(self.base_url):
            fallback = previous['payload']['fallback'] if previous else ''
        else:
            fallback = normalize_url(original, row.get('origin_url') or '')
        payload = {key: row.get(key) for key in ('id', 'subject', 'origin_url', 'shop_url_1', 'shop_url_2')}
        payload['fallback'] = fallback
        signature = hashlib.sha256(json.dumps([product_url(payload.get(key)) for key in ('shop_url_1', 'shop_url_2')]).encode()).hexdigest()
        if previous and previous['signature'] == signature:
            if not payload['fallback']:
                payload['fallback'] = previous['payload']['fallback']
            if payload != previous['payload']:
                # Affiliate tokens can change while the canonical product remains the same.
                # Publish against the current raw links without downloading or extending TTL.
                self.db.execute('UPDATE jobs SET payload=? WHERE deal_id=?', (json.dumps(payload), row['id']))
                self.db.commit()
            return self.get(row['id'])
        self.db.execute('''INSERT INTO jobs(deal_id,signature,payload,updated_at) VALUES (?,?,?,?)
            ON CONFLICT(deal_id) DO UPDATE SET signature=excluded.signature,payload=excluded.payload,
            status='pending',attempts=0,next_at=0,error='',updated_at=excluded.updated_at''',
                        (row['id'], signature, json.dumps(payload), self.now()))
        self.db.commit()
        return self.get(row['id'])

    def request_live(self, job, revision, requested_at):
        if revision <= job['live_revision']:
            return
        self.db.execute('UPDATE jobs SET live_revision=?,live_requested_at=? WHERE deal_id=?',
                        (revision, requested_at, job['deal_id']))
        self.set_meta('last_request', {'deal_id': job['deal_id'], 'revision': revision,
                                      'requested_at': requested_at, 'received_at': self.now()})

    def due(self, limit=12, *, live_only=False):
        live = "(backfill_run='' OR live_requested_at>0)"
        condition = f'AND {live}' if live_only else ''
        ids = self.db.execute(f"""SELECT deal_id FROM jobs WHERE
            status IN ('pending','failed','fallback') AND attempts<3 AND next_at<=? {condition}
            ORDER BY CASE WHEN {live} AND object_key='' THEN 0 WHEN {live} THEN 1 ELSE 2 END,
            attempts,deal_id DESC LIMIT ?""", (self.now(), limit)).fetchall()
        return [self.get(row[0]) for row in ids]

    def has_asset(self, job):
        if not job['object_key'] or job['expires_at'] <= self.now():
            return False
        try:
            return self.path(job['object_key']).stat().st_size == job['size'] > 0
        except (FileNotFoundError, ValueError):
            return False

    def repair_missing(self, job):
        if job['object_key'] and job['expires_at'] > self.now() and not self.has_asset(job):
            self.db.execute("""UPDATE jobs SET object_key='',expires_at=0,size=0,published=0,
                status='pending',attempts=0,next_at=0,error='missing_file',updated_at=? WHERE deal_id=?""",
                            (self.now(), job['deal_id']))
            self.db.commit()
            return self.get(job['deal_id'])
        return job

    def queue_backfill(self, job, run_id):
        if self.has_asset(job) or job['backfill_run'] == run_id:
            return False
        # An explicit pass may retry old exhausted jobs once. Cursor replay never resets them.
        self.db.execute("""UPDATE jobs SET backfill_run=?,status='pending',attempts=0,
            next_at=0,error='',updated_at=? WHERE deal_id=?""", (run_id, self.now(), job['deal_id']))
        self.db.commit()
        return True

    def backfill_status(self):
        state = self.meta('backfill')
        if not state:
            return {'phase': 'not_started'}
        counts = dict(self.db.execute('SELECT status,count(*) FROM jobs WHERE backfill_run=? GROUP BY status', (state['id'],)))
        active = self.db.execute("""SELECT count(*) FROM jobs WHERE backfill_run=? AND
            ((status IN ('pending','failed','fallback') AND attempts<3) OR (object_key<>'' AND published=0))""", (state['id'],)).fetchone()[0]
        saved = self.db.execute("SELECT count(*) FROM jobs WHERE backfill_run=? AND object_key<>'' AND published=1 AND expires_at>?", (state['id'], self.now())).fetchone()[0]
        if state['phase'] == 'draining' and active == 0:
            state.update(phase='complete', completed_at=self.now())
            self.set_meta('backfill', state)
        return {**state, 'jobs': sum(counts.values()), 'saved': saved, 'active': active, 'counts': counts}

    def review_community_images(self):
        if self.meta('community_review_version') == 2:
            return
        self.db.execute("""UPDATE jobs SET status='pending',attempts=0,next_at=0
            WHERE evidence='community_body' AND object_key<>'' AND expires_at>?""", (self.now(),))
        self.set_meta('community_review_version', 2)

    def path(self, key):
        if not KEY.fullmatch(key):
            raise ValueError('Invalid object key')
        return self.objects / key

    def url(self, job):
        return self.base_url + job['object_key'] if job['object_key'] else ''

    def save_image(self, job, data, size, evidence):
        digest = hashlib.sha256(data).hexdigest()[:32]
        fallback = evidence in ('community_fallback', 'community_body', 'community_body_v2')
        if self.has_asset(job) and job['object_key'].endswith('-' + digest + '.jpg'):
            self.db.execute("""UPDATE jobs SET evidence=?,status=?,attempts=attempts+1,
                next_at=?,error='',updated_at=? WHERE deal_id=?""",
                            (evidence, 'fallback' if fallback else 'ready', self.now()+1800 if fallback else 0,
                             self.now(), job['deal_id']))
            self.db.commit()
            return self.get(job['deal_id'])
        if shutil.disk_usage(self.root).free < 2 * 1024**3:
            raise ThumbnailError('storage_low')
        used = self.db.execute('SELECT COALESCE(sum(size),0) FROM jobs').fetchone()[0]
        if used + len(data) > 5 * 1024**3:
            raise ThumbnailError('storage_budget')
        expires = int(self.now()) + self.ttl_seconds
        day = datetime.fromtimestamp(expires, timezone.utc).strftime('%Y%m%d')
        key = f'{day}/{expires}-{digest}.jpg'
        path = self.path(key)
        path.parent.mkdir(exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.writing-', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.chmod(0o644)
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self.db.execute('''UPDATE jobs SET object_key=?,expires_at=?,evidence=?,size=?,width=?,height=?,
            status=?,attempts=attempts+1,next_at=?,error='',published=0,updated_at=? WHERE deal_id=?''',
                        (key, expires, evidence, len(data), size[0], size[1], 'fallback' if fallback else 'ready',
                         self.now()+1800 if fallback else 0, self.now(), job['deal_id']))
        self.db.commit()
        return self.get(job['deal_id'])

    def fail(self, job, error):
        keep = self.has_asset(job)
        self.db.execute('''UPDATE jobs SET status=?,attempts=attempts+1,next_at=?,error=?,updated_at=? WHERE deal_id=?''',
                        ('fallback' if keep else 'failed', self.now() + (300 if job['attempts'] == 0 else 3600),
                         error[:80], self.now(), job['deal_id']))
        self.db.commit()

    def mark_published(self, job):
        self.db.execute('UPDATE jobs SET published=1 WHERE deal_id=?', (job['deal_id'],))
        self.db.commit()

    def expire(self, clear_reference, limit=200):
        ids = self.db.execute('SELECT deal_id FROM jobs WHERE object_key<>\'\' AND expires_at<=? LIMIT ?', (self.now(), limit)).fetchall()
        for row in ids:
            job = self.get(row[0])
            clear_reference(job, self.url(job))
            # Clear references before removing files; a failed DB operation is retried.
            key = job['object_key']
            self.db.execute("UPDATE jobs SET status='expired',object_key='',size=0,published=0 WHERE deal_id=?", (job['deal_id'],))
            self.db.commit()
            if not self.db.execute('SELECT 1 FROM jobs WHERE object_key=? LIMIT 1', (key,)).fetchone():
                self.path(key).unlink(missing_ok=True)
        return len(ids)

    def clean_orphans(self, limit=200):
        today = datetime.fromtimestamp(self.now(), timezone.utc).strftime('%Y%m%d')
        removed = 0
        for directory in sorted(self.objects.iterdir()):
            if not directory.is_dir() or not re.fullmatch(r'[0-9]{8}', directory.name) or directory.name > today:
                continue
            for path in directory.iterdir():
                key = directory.name + '/' + path.name
                if not KEY.fullmatch(key) or int(path.name.split('-', 1)[0]) > self.now():
                    continue
                if not self.db.execute('SELECT 1 FROM jobs WHERE object_key=? LIMIT 1', (key,)).fetchone():
                    path.unlink(missing_ok=True)
                    removed += 1
                if removed >= limit:
                    return removed
            if not any(directory.iterdir()):
                directory.rmdir()
        return removed
