import json
import math
from datetime import datetime, timezone as datetime_timezone
from pathlib import Path

from django.conf import settings
from django.utils import timezone


SOURCES = (
    ('database', 'DB 서버', 'DB 데이터와 운영체제가 같은 디스크를 사용합니다.'),
    ('crawler', '크롤링 서버', '로그와 컨테이너 등 다른 파일이 디스크 공간을 함께 사용합니다.'),
)
MAX_SNAPSHOT_BYTES = 65536
STALE_SECONDS = 180


def size_label(value):
    if value is None:
        return '측정값 없음'
    size = float(value)
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB'):
        if size < 1024 or unit == 'PiB':
            return f'{size:,.1f} {unit}' if unit != 'B' else f'{int(size):,} B'
        size /= 1024


def number(value, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('Invalid number')
    if not math.isfinite(value) or value < minimum or value > 2**63 - 1:
        raise ValueError('Invalid number')
    return value


def short_text(value):
    if not isinstance(value, str) or len(value) > 512:
        raise ValueError('Invalid text')
    return value


def normalize_volume(raw):
    total = number(raw['total_bytes'], 1)
    used = number(raw['used_bytes'])
    available = number(raw['available_bytes'])
    reserved = number(raw.get('reserved_bytes', 0))
    if used + available + reserved > total + 1:
        raise ValueError('Invalid disk capacity')
    inode_total = number(raw.get('inode_total', 0))
    inode_available = number(raw.get('inode_available', 0))
    if inode_available > inode_total:
        raise ValueError('Invalid inode capacity')
    free_ratio = available / total
    inode_ratio = inode_available / inode_total if inode_total else 1
    severity = 'critical' if min(free_ratio, inode_ratio) <= .05 else (
        'warning' if min(free_ratio, inode_ratio) <= .10 else 'healthy')
    return {
        'label': short_text(raw['label']), 'path': short_text(raw['path']),
        'total': size_label(total), 'used': size_label(used),
        'available': size_label(available), 'reserved': size_label(reserved) if reserved else '',
        'used_percent': f'{used / total * 100:.1f}', 'severity': severity,
        'inode_percent': f'{inode_available / inode_total * 100:.1f}' if inode_total else '',
    }


def source_context(source, title, note, now):
    result = {'id': source, 'title': title, 'note': note, 'state': 'pending',
              'status': '측정 대기', 'message': '아직 서버의 측정 결과를 받지 못했습니다.',
              'volumes': [], 'sizes': [], 'errors': [], 'measured_at': None, 'hostname': ''}
    path = Path(settings.STORAGE_METRICS_DIR) / f'{source}.json'
    try:
        with path.open('rb') as stream:
            data = stream.read(MAX_SNAPSHOT_BYTES + 1)
        if len(data) > MAX_SNAPSHOT_BYTES:
            raise ValueError('Snapshot too large')
        snapshot = json.loads(data)
        report = snapshot.get('report')
        if not report:
            if snapshot.get('error'):
                result.update(state='error', status='연결 오류',
                              message='서버의 측정 결과를 가져오지 못했습니다. 다음 자동 수집 때 다시 확인합니다.')
            return result
        if report['version'] != 1 or report['source'] != source:
            raise ValueError('Invalid source')
        measured = number(report['measured_at'], 1)
        received = number(snapshot['received_at'], 1)
        if max(measured, received) > now.timestamp() + 120:
            raise ValueError('Future measurement')
        volumes = [normalize_volume(v) for v in report['volumes']]
        if len(volumes) > 16 or len(report['sizes']) > 16 or len(report['errors']) > 16:
            raise ValueError('Too many measurements')
        sizes = [{'label': short_text(s['label']),
                  'size': size_label(number(s['bytes'])) if s['bytes'] is not None else '측정값 없음'}
                 for s in report['sizes']]
        errors = [short_text(e) for e in report['errors']]
        result.update(volumes=volumes, sizes=sizes, errors=errors,
                      hostname=short_text(report['hostname']),
                      measured_at=datetime.fromtimestamp(measured, datetime_timezone.utc),
                      state='healthy', status='정상', message='최근 측정값입니다.')
        if any(v['severity'] == 'critical' for v in volumes):
            result.update(state='critical', status='공간 부족', message='디스크 또는 파일 생성 여유가 5% 이하입니다.')
        elif any(v['severity'] == 'warning' for v in volumes):
            result.update(state='warning', status='용량 주의', message='디스크 또는 파일 생성 여유가 10% 이하입니다.')
        if errors or not volumes:
            result.update(state='error', status='일부 측정 실패', message='측정하지 못한 항목이 있습니다. 확인된 값만 표시합니다.')
        if snapshot.get('error'):
            result.update(state='error', status='연결 오류', message='서버 연결에 실패했습니다. 마지막으로 받은 측정값입니다.')
        if now.timestamp() - min(measured, received) > STALE_SECONDS:
            result.update(state='stale', status='갱신 지연', message='3분 이상 갱신되지 않았습니다. 현재 용량과 다를 수 있습니다.')
        return result
    except FileNotFoundError:
        return result
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
        result.update(state='error', status='측정 오류', message='측정 결과를 읽을 수 없습니다. 다음 자동 수집 때 다시 확인합니다.')
        return result


def storage_context():
    now = timezone.now()
    return {'checked_at': now, 'sources': [source_context(*source, now) for source in SOURCES]}
