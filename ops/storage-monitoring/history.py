#!/usr/bin/env python3
"""Bounded, incremental, redacted log history. Only timers call Docker/SSH."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import time
import uuid

from logs import bounded_command, redact

MAX_PAGES = 16384  # 64 MiB, plus a transient rollback journal.
TARGET_PAGES = 12288
RETENTION_US = 7 * 86400 * 1000000
TRANSFER_BYTES = 1024 * 1024
SOURCE_BYTES = 1024 * 1024
SOURCE_NAMES = ('crawler', 'flaresolverr', 'vpn', 'cleanup')
ATTENTION = re.compile(r'\b(ERROR|CRITICAL|FATAL|WARNING|WARN|Traceback|\w*Exception)\b', re.I)
ERROR = re.compile(r'\b(ERROR|CRITICAL|FATAL|Traceback|\w*Exception)\b', re.I)


def connect(path):
    path = Path(path)
    db = sqlite3.connect(path, timeout=.5)
    db.execute('PRAGMA page_size=4096')
    db.execute('PRAGMA auto_vacuum=INCREMENTAL')
    db.execute('PRAGMA journal_mode=DELETE')
    db.execute('PRAGMA cache_size=-2048')
    db.execute('PRAGMA max_page_count=' + str(MAX_PAGES))
    db.executescript('''
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, ts INTEGER NOT NULL,
            severity TEXT NOT NULL, text TEXT NOT NULL, fingerprint TEXT UNIQUE);
        CREATE INDEX IF NOT EXISTS events_source_time ON events(source, ts DESC, id DESC);
        CREATE INDEX IF NOT EXISTS events_time ON events(ts);
        CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    ''')
    db.execute("INSERT OR IGNORE INTO metadata VALUES ('generation', ?)", (json.dumps(uuid.uuid4().hex),))
    db.commit()
    path.chmod(0o644)
    return db


def meta(db, key, default=None):
    row = db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else default


def set_meta(db, key, value):
    db.execute('INSERT OR REPLACE INTO metadata VALUES (?, ?)', (key, json.dumps(value)))


def retain(db, now_us):
    db.execute('DELETE FROM events WHERE ts < ?', (now_us - RETENTION_US,))
    for _ in range(64):
        used = db.execute('PRAGMA page_count').fetchone()[0] - db.execute('PRAGMA freelist_count').fetchone()[0]
        if used <= TARGET_PAGES:
            break
        db.execute('DELETE FROM events WHERE id IN (SELECT id FROM events ORDER BY ts, id LIMIT 2000)')
    db.commit()
    db.execute('PRAGMA incremental_vacuum(128)')


def timestamp_us(value):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('Timestamp needs timezone')
    return int(dt.timestamp() * 1000000)


def source_command(name, since, until):
    start = f'{since / 1000000:.6f}'
    end = f'{until / 1000000:.6f}'
    if name in ('crawler', 'flaresolverr'):
        container = 'crawlers-bot' if name == 'crawler' else 'flaresolverr'
        return ['docker', 'logs', '--timestamps', '--since', start, '--until', end, container]
    unit = {'vpn': 'ppomppu-vpn-guard.service', 'cleanup': 'geteverything-log-maintenance.service'}[name]
    return ['journalctl', '-u', unit, '--since', '@' + start, '--until', '@' + end,
            '--no-pager', '-o', 'json', '--output-fields=__CURSOR,__REALTIME_TIMESTAMP,MESSAGE']


def parse_line(name, raw):
    if name in ('crawler', 'flaresolverr'):
        stamp, message_bytes = raw.split(b' ', 1)
        ts = timestamp_us(stamp.decode('ascii'))
        message = message_bytes.decode('utf-8', 'replace') if len(message_bytes) <= 8192 else '[긴 로그 항목 생략]'
        identity = stamp.decode('ascii') + ' ' + message if len(message_bytes) <= 8192 else stamp.decode('ascii') + ':' + hashlib.sha256(message_bytes).hexdigest()
    else:
        record = json.loads(raw)
        ts = int(record['__REALTIME_TIMESTAMP'])
        message = record.get('MESSAGE', '')
        if not isinstance(message, str):
            message = '[바이너리 로그 생략]'
        elif len(message) > 8192:
            message = '[긴 로그 항목 생략]'
        identity = record['__CURSOR']
    return ts, message, identity


def collect_source(db, name, now_us):
    state = meta(db, 'source:' + name, {})
    cursor = state.get('cursor', now_us - 86400 * 1000000)
    since = max(cursor - 2000000, now_us - RETENTION_US)
    old_cursor = cursor
    private_key = state.get('private_key', False)
    skipped = 0
    try:
        raw, truncated, code = bounded_command(source_command(name, since, now_us),
                                                limit=SOURCE_BYTES, timeout=5)
        if code not in (0, None):
            raise ValueError('Source failed')
        # A truncated transport's last partial record is retried from its timestamp.
        if truncated:
            raw = raw.rsplit(b'\n', 1)[0] if b'\n' in raw else b''
        occurrences = {}
        for line in raw.splitlines():
            if not line or line == b'-- No entries --':
                continue
            try:
                ts, message, identity = parse_line(name, line)
                if not since <= ts <= now_us + 1000000:
                    raise ValueError('Out of range')
            except (ValueError, TypeError, KeyError):
                skipped += 1
                continue
            # Exact duplicate timestamps can contain multiple identical messages.
            digest = hashlib.sha256((name + identity).encode()).hexdigest()
            occurrences[digest] = occurrences.get(digest, 0) + 1
            fingerprint = digest + ':' + str(occurrences[digest])
            if '-----BEGIN ' in message and 'PRIVATE KEY-----' in message:
                private_key = True
            if private_key:
                text = '[PRIVATE KEY REDACTED]'
                if '-----END ' in message and 'PRIVATE KEY-----' in message:
                    private_key = False
            else:
                text = '\n'.join(redact(message.encode()))[:2100]
            severity = 'error' if ERROR.search(text) else ('warning' if ATTENTION.search(text) else 'info')
            db.execute('INSERT OR IGNORE INTO events(source,ts,severity,text,fingerprint) VALUES (?,?,?,?,?)',
                       (name, ts, severity, text, fingerprint))
            cursor = max(cursor, ts)
        if truncated and cursor <= old_cursor:
            raise ValueError('Oversized record prevents progress')
        state.update(cursor=cursor if truncated else now_us, checked_at=time.time(), error=None,
                     catching_up=truncated, private_key=private_key, skipped=skipped)
    except (OSError, ValueError, subprocess.SubprocessError):
        state.update(error='로그 이력 수집에 실패했습니다. 다음 수집 때 다시 시도합니다.', checked_at=time.time())
    set_meta(db, 'source:' + name, state)
    db.commit()
    return bool(state.get('catching_up')) and not state.get('error')


def collect(path):
    now_us = int(time.time() * 1000000)
    with closing(connect(path)) as db:
        retain(db, now_us)
        pending = [collect_source(db, name, now_us) for name in SOURCE_NAMES]
        set_meta(db, 'collected_at', time.time())
        db.commit()
        return any(pending)


def export_page(path, after):
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=.5)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('PRAGMA cache_size=-2048')
        db.execute('BEGIN')
        rows = []
        used = 0
        for row in db.execute('SELECT id,source,ts,severity,text FROM events WHERE id>? ORDER BY id LIMIT 1000', (after,)):
            size = len(json.dumps(row, ensure_ascii=False).encode()) + 2
            if used + size > TRANSFER_BYTES - 32768:
                break
            used += size
            rows.append(row)
        last = rows[-1][0] if rows else after
        sources = {}
        for name in SOURCE_NAMES:
            state = meta(db, 'source:' + name, {})
            oldest = db.execute('SELECT ts FROM events WHERE source=? ORDER BY ts LIMIT 1', (name,)).fetchone()
            state['retained_from'] = oldest[0] if oldest else None
            sources[name] = state
        return {'version': 1, 'generation': meta(db, 'generation'), 'rows': rows, 'next_id': last,
                'has_more': bool(db.execute('SELECT 1 FROM events WHERE id>? LIMIT 1', (last,)).fetchone()),
                'collected_at': meta(db, 'collected_at', 0),
                'sources': sources}


def validate_page(page, after):
    if page['version'] != 1 or not re.fullmatch('[0-9a-f]{32}', page['generation']):
        raise ValueError('Invalid generation')
    if not isinstance(page['rows'], list) or len(page['rows']) > 1000:
        raise ValueError('Invalid rows')
    previous = after
    for row in page['rows']:
        if not isinstance(row, list) or len(row) != 5:
            raise ValueError('Invalid row')
        identity, name, ts, severity, text = row
        if type(identity) is not int or not previous < identity < 2**63:
            raise ValueError('Invalid identity')
        if name not in SOURCE_NAMES or type(ts) is not int or not 0 < ts <= (time.time()+120)*1000000:
            raise ValueError('Invalid source/time')
        if severity not in ('info', 'warning', 'error') or not isinstance(text, str) or len(text) > 2100:
            raise ValueError('Invalid content')
        previous = identity
    if type(page['next_id']) is not int or page['next_id'] != previous or type(page['has_more']) is not bool:
        raise ValueError('Invalid cursor')
    if set(page['sources']) != set(SOURCE_NAMES):
        raise ValueError('Invalid source status')


def synchronize(config, max_pages=2):
    source = next(s for s in config['sources'] if s['source'] == 'crawler')
    path = Path(config['state_directory']) / 'snapshots' / 'log-history.sqlite3'
    with closing(connect(path)) as db:
        retain(db, int(time.time()*1000000))
        for _ in range(max_pages):
            after = meta(db, 'received_id', 0)
            try:
                raw, cut, code = bounded_command([
                    'ssh', '-F', '/dev/null', '-i', config['identity_file'], '-o', 'BatchMode=yes',
                    '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=5',
                    '-o', 'ConnectionAttempts=1', '-o', 'ServerAliveInterval=3', '-o', 'ServerAliveCountMax=1',
                    '-o', 'LogLevel=ERROR', '-o', f"UserKnownHostsFile={config['known_hosts_file']}",
                    source['target'], 'history ' + str(after)], limit=TRANSFER_BYTES, timeout=12)
                if cut or code:
                    raise ValueError('Incomplete history')
                page = json.loads(raw)
                generation = meta(db, 'source_generation')
                if generation and generation != page.get('generation'):
                    # Reset only this disposable cache, after validating a new epoch.
                    validate_page(page, after)
                    db.execute('DELETE FROM events')
                    set_meta(db, 'received_id', 0)
                    set_meta(db, 'source_generation', page['generation'])
                    db.commit()
                    continue
                validate_page(page, after)
                db.executemany('INSERT OR IGNORE INTO events(id,source,ts,severity,text) VALUES (?,?,?,?,?)', page['rows'])
                set_meta(db, 'generation', page['generation'])
                set_meta(db, 'source_generation', page['generation'])
                set_meta(db, 'received_id', page['next_id'])
                set_meta(db, 'received_at', time.time())
                set_meta(db, 'collected_at', page['collected_at'])
                set_meta(db, 'sync_pending', page['has_more'])
                set_meta(db, 'error', None)
                for name, state in page['sources'].items():
                    oldest = state.get('retained_from')
                    if type(oldest) is int and oldest > 0:
                        db.execute('DELETE FROM events WHERE source=? AND ts<?', (name, oldest))
                    set_meta(db, 'source:' + name, state)
                db.commit()
                if not page['has_more']:
                    return False
            except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
                db.rollback()
                set_meta(db, 'error', '로그 이력 연결에 실패했습니다. 마지막으로 받은 내용을 표시합니다.')
                db.commit()
                return False
        return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rounds', type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.rounds <= 200:
        raise ValueError('Invalid round count')
    config = json.loads(Path('/etc/geteverything-storage/config.json').read_text())
    for _ in range(args.rounds):
        if config['source'] == 'crawler':
            pending = collect(Path(config['state_directory']) / 'log-history.sqlite3')
        elif config['source'] == 'hub':
            pending = synchronize(config)
        else:
            raise ValueError('Unsupported host')
        if not pending:
            break
        print(json.dumps({'source': config['source'], 'round': _+1, 'catching_up': True}), flush=True)
    print(json.dumps({'source': config['source'], 'catching_up': pending}))


if __name__ == '__main__':
    main()
