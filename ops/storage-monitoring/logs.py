#!/usr/bin/env python3
"""Small, redacted snapshots. No follow mode, arbitrary paths, or web-request SSH."""
import json
import os
from pathlib import Path
import re
import selectors
import subprocess
import time

from collect import atomic_json

MAX_BYTES = 64 * 1024
MAX_REPORT_BYTES = 1024 * 1024
MAX_LINES = 300
SOURCES = {
    'crawler': ['docker', 'logs', '--timestamps', '--since', '1h', '--tail', '300', 'crawlers-bot'],
    'flaresolverr': ['docker', 'logs', '--timestamps', '--since', '1h', '--tail', '300', 'flaresolverr'],
    'vpn': ['journalctl', '-u', 'ppomppu-vpn-guard.service', '--since', '1 hour ago',
            '-n', '300', '--no-pager', '-o', 'short-iso'],
    'cleanup': ['journalctl', '-u', 'geteverything-log-maintenance.service', '--since', '24 hours ago',
                '-n', '300', '--no-pager', '-o', 'short-iso'],
}
ANSI = re.compile(r'\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))')
CONTROL = re.compile(r'[\x00-\x08\x0b-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]')
PRIVATE_KEY = re.compile(r'-----BEGIN [^\n]*PRIVATE KEY-----.*?(?:-----END [^\n]*PRIVATE KEY-----|\Z)', re.S)
ASSIGNMENT = re.compile(r'''(?<![A-Za-z0-9_-])["']?([A-Za-z0-9_-]{1,128})["']?\s*[:=]\s*''')
SECRET_NAMES = ('authorization', 'cookie', 'password', 'passwd', 'pwd', 'secret', 'secret_access_key',
                'token', 'api_key', 'apikey', 'session', 'sessionid', 'csrfmiddlewaretoken')
USERINFO = re.compile(r'(?i)([a-z][a-z0-9+.-]{0,15}://)[^\s/@]+@')
JWT = re.compile(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b')


def bounded_command(args, limit=MAX_BYTES, timeout=3):
    """Bound both output and wall time, including a child that never closes stdout."""
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               stdin=subprocess.DEVNULL, start_new_session=True)
    output = bytearray()
    truncated = False
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(args[0], timeout)
                if not selector.select(remaining):
                    raise subprocess.TimeoutExpired(args[0], timeout)
                chunk = os.read(process.stdout.fileno(), min(8192, limit + 1 - len(output)))
                if not chunk:
                    code = process.wait(timeout=max(.01, deadline - time.monotonic()))
                    return bytes(output), False, code
                output.extend(chunk)
                if len(output) > limit:
                    truncated = True
                    return bytes(output[:limit]), truncated, None
    finally:
        # Kill the session too: a child may inherit stdout after its parent exits.
        try:
            os.killpg(process.pid, 9)
        except ProcessLookupError:
            pass
        process.wait(timeout=1)
        process.stdout.close()


def redact(raw):
    text = raw.decode('utf-8', errors='replace')
    text = PRIVATE_KEY.sub('[PRIVATE KEY REDACTED]', text)
    text = CONTROL.sub('', ANSI.sub('', text))
    text = USERINFO.sub(r'\1[REDACTED]@', text)
    text = JWT.sub('[TOKEN REDACTED]', text)
    text = re.sub(r'(?i)\bBearer\s+[^\s,;]+', 'Bearer [REDACTED]', text)
    lines = []
    for line in text.splitlines()[-MAX_LINES:]:
        for match in ASSIGNMENT.finditer(line):
            key = match[1].lower().replace('-', '_')
            if key in SECRET_NAMES or key.endswith(tuple('_' + name for name in SECRET_NAMES)):
                line = line[:match.start()] + '[SENSITIVE VALUE REDACTED]'
                break
        lines.append(line[:2048] + (' … [긴 줄 생략]' if len(line) > 2048 else ''))
    return lines


def collect(state_directory):
    report = {'version': 1, 'source': 'crawler-logs', 'measured_at': time.time(), 'sources': []}
    previous = {}
    try:
        with (Path(state_directory) / 'logs.json').open('rb') as stream:
            old = json.loads(stream.read(MAX_REPORT_BYTES + 1))
        previous = {s['id']: s for s in old['sources']}
    except (OSError, ValueError, KeyError, TypeError):
        pass
    for name, command in SOURCES.items():
        source = {'id': name, 'lines': [], 'truncated': False, 'error': None, 'measured_at': time.time()}
        try:
            raw, truncated, code = bounded_command(command)
            if code not in (0, None):
                raise ValueError('Source command failed')
            source.update(lines=[] if raw.strip() == b'-- No entries --' else redact(raw), truncated=truncated)
        except (OSError, ValueError, subprocess.SubprocessError):
            if name in previous:
                source = previous[name].copy()
            source['error'] = '로그를 수집하지 못했습니다. 다음 수집 때 다시 확인합니다.'
        report['sources'].append(source)
    atomic_json(Path(state_directory) / 'logs.json', report)
    print(json.dumps({'sources': len(report['sources']),
                      'errors': sum(bool(s['error']) for s in report['sources'])}))


def pull(config, source):
    path = Path(config['state_directory']) / 'snapshots' / 'crawler-logs.json'
    previous = {}
    try:
        with path.open('rb') as stream:
            previous = json.loads(stream.read(MAX_REPORT_BYTES + 1))
        if not isinstance(previous, dict):
            previous = {}
    except (OSError, ValueError):
        pass
    now = time.time()
    try:
        raw, truncated, code = bounded_command([
            'ssh', '-F', '/dev/null', '-i', config['identity_file'], '-o', 'BatchMode=yes',
            '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=5',
            '-o', 'ConnectionAttempts=1', '-o', 'ServerAliveInterval=3', '-o', 'ServerAliveCountMax=1',
            '-o', 'LogLevel=ERROR', '-o', f"UserKnownHostsFile={config['known_hosts_file']}",
            source['target'], 'logs'], limit=MAX_REPORT_BYTES, timeout=12)
        if truncated or code:
            raise ValueError('Incomplete log snapshot')
        report = json.loads(raw)
        if report['version'] != 1 or report['source'] != 'crawler-logs':
            raise ValueError('Wrong log snapshot')
        measured = report['measured_at']
        if isinstance(measured, bool) or not isinstance(measured, (int, float)) or not 0 < measured <= now + 120:
            raise ValueError('Invalid measurement time')
        previous = {'report': report, 'received_at': now, 'error': None}
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        previous['error'] = '로그 서버 연결에 실패했습니다.'
    previous['last_attempt_at'] = now
    atomic_json(path, previous)
    print(json.dumps({'source': 'crawler-logs', 'received': not bool(previous.get('error'))}))


if __name__ == '__main__':
    collect('/var/lib/geteverything-storage')
