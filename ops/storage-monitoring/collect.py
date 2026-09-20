#!/usr/bin/env python3
"""Bounded host measurements and read-only SSH snapshot collection."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time


def atomic_json(path, data):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix='.storage-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, ensure_ascii=False, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fchmod(stream.fileno(), 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def run(args, timeout=8, env=None):
    return subprocess.run(args, capture_output=True, text=True, check=True,
                          timeout=timeout, env=env).stdout


def filesystem(path, label):
    resolved = Path(path).resolve(strict=True)
    stat = os.statvfs(resolved)
    total = stat.f_blocks * stat.f_frsize
    free = stat.f_bfree * stat.f_frsize
    available = stat.f_bavail * stat.f_frsize
    return {
        'label': label, 'path': str(resolved), 'total_bytes': total,
        'used_bytes': total - free, 'available_bytes': available,
        'reserved_bytes': max(0, free - available),
        'inode_total': stat.f_files, 'inode_available': stat.f_favail,
    }


def disk_volumes(paths, errors):
    volumes, devices = [], set()
    for label, path in paths:
        try:
            device = os.stat(path).st_dev
            if device not in devices:
                volumes.append(filesystem(path, label))
                devices.add(device)
        except OSError:
            errors.append(f'{label}의 디스크 용량을 측정하지 못했습니다.')
    return volumes


def allocated_size(paths):
    paths = list(paths)
    if not paths:
        return 0
    output = run(['du', '-s', '-x', '-B1', '--', *map(str, paths)], timeout=10)
    return sum(int(line.split()[0]) for line in output.splitlines())


def database(config, report):
    data_dir = config['data_directory']
    paths = [('DB 데이터 디스크', data_dir), ('DB WAL 디스크', str(Path(data_dir) / 'pg_wal'))]
    size = None
    query = """SELECT json_build_object(
        'database_bytes', pg_database_size(current_database()),
        'data_directory', current_setting('data_directory'),
        'tablespaces', (SELECT COALESCE(json_agg(pg_tablespace_location(oid)), '[]'::json)
            FROM pg_tablespace WHERE pg_tablespace_location(oid) <> ''))"""
    try:
        env = {**os.environ, 'PGOPTIONS': '-c statement_timeout=5000 -c default_transaction_read_only=on',
               'PGCONNECT_TIMEOUT': '3'}
        value = json.loads(run(['runuser', '-u', 'postgres', '--', 'psql', '-X', '-A', '-t',
                                '-v', 'ON_ERROR_STOP=1', '-d', config['database_name'], '-c', query], env=env))
        size = value['database_bytes']
        data_dir = value['data_directory']
        paths = [('DB 데이터 디스크', data_dir), ('DB WAL 디스크', str(Path(data_dir) / 'pg_wal'))]
        paths += [('DB 테이블스페이스 디스크', p) for p in value['tablespaces']]
    except (OSError, subprocess.SubprocessError, ValueError, KeyError):
        report['errors'].append('DB 데이터 크기를 조회하지 못했습니다.')
    report['sizes'] = [{'label': f"{config['database_name']} DB 데이터", 'bytes': size}]
    report['volumes'] = disk_volumes(paths, report['errors'])


def crawler(config, report):
    paths = [('크롤러 로그 디스크', config['log_directory'])]
    for label, path in (('크롤러 파일 로그', config['log_directory']), ('시스템 로그', '/var/log')):
        size = None
        try:
            size = allocated_size([path])
            paths.append((label + ' 디스크', path))
        except (OSError, subprocess.SubprocessError, ValueError):
            report['errors'].append(f'{label} 사용량을 측정하지 못했습니다.')
        report['sizes'].append({'label': label, 'bytes': size})
    size = None
    try:
        docker_root = Path(run(['docker', 'info', '--format', '{{.DockerRootDir}}']).strip())
        if not docker_root.is_absolute() or str(docker_root) == '/':
            raise ValueError('Invalid Docker path')
        paths.append(('컨테이너 로그 디스크', str(docker_root)))
        containers = docker_root / 'containers'
        logs = list(containers.glob('*/local-logs')) + list(containers.glob('*/*-json.log*'))
        size = allocated_size(logs)
    except (OSError, subprocess.SubprocessError, ValueError):
        report['errors'].append('컨테이너 로그 사용량을 측정하지 못했습니다.')
    report['sizes'].append({'label': '컨테이너 로그 (중지된 컨테이너 포함)', 'bytes': size})
    report['volumes'] = disk_volumes(paths, report['errors'])


def collect_source(config):
    source = config['source']
    report = {'version': 1, 'source': source, 'measured_at': time.time(),
              'hostname': socket.gethostname(), 'volumes': [], 'sizes': [], 'errors': []}
    {'database': database, 'crawler': crawler}[source](config, report)
    atomic_json(Path(config['state_directory']) / 'report.json', report)
    print(json.dumps({'source': source, 'errors': len(report['errors']), 'volumes': len(report['volumes'])}))


def pull(config, source):
    name = source['source']
    if name not in ('database', 'crawler'):
        raise ValueError('Invalid source')
    path = Path(config['state_directory']) / 'snapshots' / f'{name}.json'
    try:
        previous = json.loads(path.read_text()) if path.exists() else {}
    except (OSError, ValueError):
        previous = {}
    now = time.time()
    try:
        payload = run(['ssh', '-F', '/dev/null', '-i', config['identity_file'],
                       '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
                       '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=5',
                       '-o', 'ConnectionAttempts=1', '-o', 'ServerAliveInterval=3',
                       '-o', 'ServerAliveCountMax=1', '-o', 'LogLevel=ERROR',
                       '-o', f"UserKnownHostsFile={config['known_hosts_file']}",
                       source['target']], timeout=12)
        if len(payload.encode()) > 65536:
            raise ValueError('Oversized report')
        report = json.loads(payload)
        if report['source'] != name or report['version'] != 1:
            raise ValueError('Invalid report')
        measured = report['measured_at']
        if isinstance(measured, bool) or not isinstance(measured, (int, float)) or not 0 < measured <= now + 120:
            raise ValueError('Invalid measurement time')
        previous = {'report': report, 'received_at': now, 'error': None}
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        previous['error'] = '서버의 측정 결과를 가져오지 못했습니다.'
    previous['last_attempt_at'] = now
    atomic_json(path, previous)
    print(json.dumps({'source': name, 'received': not bool(previous.get('error'))}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='/etc/geteverything-storage/config.json')
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    if config['source'] == 'hub':
        for source in config['sources']:
            pull(config, source)
        if config.get('collect_logs'):
            from logs import pull as pull_logs
            for source in config['sources']:
                if source['source'] == 'crawler':
                    pull_logs(config, source)
    else:
        collect_source(config)


if __name__ == '__main__':
    main()
