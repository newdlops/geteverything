from contextlib import closing
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core import signing
from django.utils import timezone

SOURCES = (('crawler', '크롤러'), ('flaresolverr', 'FlareSolverr'),
           ('vpn', '뽐뿌 VPN 관리'), ('cleanup', '로그 자동 정리'))
PAGE_SIZE = 200
MAX_DATABASE_BYTES = 64 * 1024 * 1024
KST = ZoneInfo('Asia/Seoul')
CURSOR_SALT = 'monitoring.log-history.v1'


class QueryError(ValueError):
    def __init__(self, field, message):
        self.field = field
        super().__init__(message)


def parse_time(value, field):
    try:
        if len(value) > 32:
            raise ValueError
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is not None:
            raise ValueError
        return int(parsed.replace(tzinfo=KST).timestamp() * 1000000)
    except (ValueError, OverflowError):
        raise QueryError(field, '한국 시간으로 올바른 날짜와 시각을 입력해 주세요.')


def at_time(value):
    return datetime.fromtimestamp(value / 1000000, KST) if value is not None else None


def metadata(db, key, default=None):
    row = db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else default


def log_context(params):
    now = timezone.now()
    source = params.get('source', 'crawler')
    if source not in dict(SOURCES):
        source = 'crawler'
    start = params.get('start', (now.astimezone(KST) - timedelta(hours=1)).replace(microsecond=0).isoformat()[:19])
    end = params.get('end', '')
    query = params.get('q', '').strip()[:120]
    level = 'attention' if params.get('level') == 'attention' else 'all'
    result = {'log_sources': SOURCES, 'selected_source': source, 'source_title': dict(SOURCES)[source],
              'query': query, 'level': level, 'start_value': start[:32], 'end_value': end[:32],
              'checked_at': now, 'measured_at': None, 'lines': [], 'next_cursor': '',
              'available_from': None, 'available_to': None, 'displayed_count': 0,
              'http_status': 200, 'state': 'pending', 'status': '이력 수집 대기',
              'message': '아직 로그 이력을 받지 못했습니다. 잠시 후 다시 조회해 주세요.',
              'form_errors': {}, 'outside_retention': False}
    try:
        if not start:
            raise QueryError('start', '조회 시작 시각을 입력해 주세요.')
        start_us = parse_time(start, 'start')
        range_end = parse_time(end, 'end') if end else int(now.timestamp()*1000000)
        end_us = range_end + 999999 if end else range_end
        if start_us > end_us:
            raise QueryError('end', '종료 시각은 시작 시각 이후여야 합니다.')
        if range_end - start_us > 7 * 86400 * 1000000:
            raise QueryError('start', '한 번에 최대 7일 범위를 조회할 수 있습니다.')
        fingerprint = hashlib.sha256(json.dumps([source, query, level, start_us, end], ensure_ascii=False).encode()).hexdigest()
        token = params.get('cursor', '')
        cursor = None
        if token:
            try:
                if len(token) > 2048:
                    raise ValueError
                cursor = signing.loads(token, salt=CURSOR_SALT, max_age=3600)
                if cursor['filter'] != fingerprint:
                    raise ValueError
                for name in ('anchor', 'last_ts', 'last_id', 'offset', 'end'):
                    if type(cursor[name]) is not int or not 0 <= cursor[name] < 2**63:
                        raise ValueError
                end_us = cursor['end']
            except (ValueError, KeyError, TypeError, signing.BadSignature):
                raise QueryError('cursor', '조회 조건이 바뀌었거나 조회가 만료됐습니다. 다시 조회해 주세요.')
        path = Path(settings.STORAGE_METRICS_DIR) / 'log-history.sqlite3'
        if not path.exists():
            return result
        if path.stat().st_size > MAX_DATABASE_BYTES:
            raise ValueError('Oversized history database')
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=.2)) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('PRAGMA cache_size=-2048')
            deadline = time.monotonic() + .75
            db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            db.create_function('casefold', 1, lambda text: text.casefold(), deterministic=True)
            db.execute('BEGIN')
            generation = metadata(db, 'generation')
            if cursor and cursor['generation'] != generation:
                raise QueryError('cursor', '로그 보관 정보가 변경됐습니다. 다시 조회해 주세요.')
            anchor = cursor['anchor'] if cursor else db.execute('SELECT COALESCE(MAX(id),0) FROM events').fetchone()[0]
            offset = cursor['offset'] if cursor else 0
            oldest = db.execute('SELECT ts FROM events WHERE source=? ORDER BY ts LIMIT 1', (source,)).fetchone()
            newest = db.execute('SELECT ts FROM events WHERE source=? ORDER BY ts DESC LIMIT 1', (source,)).fetchone()
            clauses = ['source=?', 'ts>=?', 'ts<=?', 'id<=?']
            values = [source, start_us, end_us, anchor]
            if cursor:
                clauses.append('(ts<? OR (ts=? AND id<?))')
                values.extend([cursor['last_ts'], cursor['last_ts'], cursor['last_id']])
            if query:
                clauses.append('instr(casefold(text),?)>0')
                values.append(query.casefold())
            if level == 'attention':
                clauses.append("severity IN ('warning','error')")
            rows = db.execute('SELECT id,ts,severity,text FROM events WHERE ' + ' AND '.join(clauses) +
                              ' ORDER BY ts DESC,id DESC LIMIT ?', [*values, PAGE_SIZE+1]).fetchall()
            lines = []
            for index, (identity, ts, severity, text) in enumerate(rows[:PAGE_SIZE], offset+1):
                if severity not in ('info', 'warning', 'error') or not isinstance(text, str) or len(text) > 2100:
                    raise ValueError('Invalid log entry')
                lines.append({'id': identity, 'number': index, 'time': at_time(ts),
                              'severity': severity, 'text': text})
            next_cursor = ''
            if len(rows) > PAGE_SIZE:
                identity, ts, _, _ = rows[PAGE_SIZE-1]
                next_cursor = signing.dumps({'generation': generation, 'filter': fingerprint,
                    'anchor': anchor, 'last_ts': ts, 'last_id': identity,
                    'offset': offset+PAGE_SIZE, 'end': end_us}, salt=CURSOR_SALT, compress=True)
            state = metadata(db, 'source:' + source, {})
            received = metadata(db, 'received_at', 0)
            result.update(state='healthy', status='조회 완료', message='최신 로그부터 표시합니다. 아래로 내리면 이전 로그를 불러옵니다.',
                          lines=lines, next_cursor=next_cursor, displayed_count=offset+len(lines),
                          available_from=at_time(oldest[0]) if oldest else None,
                          available_to=at_time(newest[0]) if newest else None,
                          outside_retention=bool(oldest and start_us < oldest[0]),
                          measured_at=at_time(int(state.get('checked_at', 0)*1000000)) if state.get('checked_at') else None)
            if metadata(db, 'error') or state.get('error'):
                result.update(state='error', status='수집 오류', message='최신 이력을 가져오지 못했습니다. 마지막으로 받은 로그를 조회합니다.')
            elif metadata(db, 'sync_pending') or state.get('catching_up'):
                result.update(state='stale', status='이력 동기화 중', message='이전 로그를 가져오는 중입니다. 현재 저장된 범위부터 조회합니다.')
            elif now.timestamp() - min(received, state.get('checked_at', 0)) > 180:
                result.update(state='stale', status='갱신 지연', message='3분 이상 갱신되지 않았습니다. 마지막 수집 시각을 확인해 주세요.')
            elif state.get('skipped'):
                result.update(state='stale', status='일부 로그 생략', message='형식을 읽지 못한 항목이 있습니다. 확인 가능한 로그만 표시합니다.')
        return result
    except QueryError as error:
        result.update(state='invalid', status='조회 조건 확인', message=str(error),
                      form_errors={error.field: str(error)}, http_status=400)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError, sqlite3.Error):
        result.update(state='error', status='조회 오류', lines=[], next_cursor='', http_status=503,
                      message='로그 조회가 지연되거나 이력을 읽을 수 없습니다. 범위를 줄여 다시 조회해 주세요.')
    return result
