#!/usr/bin/env python3
"""Maintain a loopback-only Ppomppu proxy in a separate VPN network namespace."""
import base64
from collections import Counter
import csv
import fcntl
import gzip
import hashlib
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import time
import urllib.error
import urllib.request
import zlib

NAME = 'ppomppu-vpn'
LABEL = 'geteverything.ppomppu-vpn'
IMAGE = 'ppomppu-vpngate:20260914'
ROOT = Path('/var/lib/ppomppu-vpn')
CONFIG = Path('/etc/ppomppu-vpn')
URL = 'https://www.ppomppu.co.kr/zboard/zboard.php?id=ppomppu&page=1&divpage=96'
PROXY = 'http://127.0.0.1:18888'
DOMAINS = ('www.ppomppu.co.kr', 'm.ppomppu.co.kr')
CATALOG_REFRESH_SECONDS = 300
CATALOG_MAX_AGE_SECONDS = 86400
LAST_PROBE = {}
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36'


def run(args, *, timeout=20, check=True):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=check)


def write_private(path, text):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(text)
    temporary.chmod(0o600)
    temporary.replace(path)


def read_json(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def validate_relay(relay):
    address = ipaddress.ip_address(relay['ip'])
    if address.version != 4 or not address.is_global:
        raise ValueError('Relay must have a public IPv4 address')
    if relay['proto'] not in ('tcp', 'tcp-client', 'udp') or not 1 <= int(relay['port']) <= 65535:
        raise ValueError('Invalid relay transport')
    for name in ('ca', 'cert', 'key'):
        pem = relay['blocks'][name].strip()
        match = re.fullmatch(r'-----BEGIN ([A-Z ]+)-----\s+[A-Za-z0-9+/=\r\n]+-----END \1-----', pem)
        allowed = {'PRIVATE KEY', 'RSA PRIVATE KEY', 'EC PRIVATE KEY'} if name == 'key' else {'CERTIFICATE'}
        if not match or match.group(1) not in allowed:
            raise ValueError('Invalid relay PEM block')
    return relay


def parse_relays(text):
    lines = text.lstrip('\ufeff').splitlines()
    if len(lines) < 2 or not lines[0].startswith('*vpn_servers') or not lines[1].startswith('#HostName,IP,'):
        raise ValueError('Unexpected VPN Gate response')
    rows = csv.DictReader(io.StringIO('\n'.join([lines[1][1:]] + [s for s in lines[2:] if s and not s.startswith('*')])))
    candidates = []
    for row in rows:
        if not re.fullmatch(r'[A-Z]{2}', row.get('CountryShort', '')):
            continue
        try:
            profile = base64.b64decode(row['OpenVPN_ConfigData_Base64'], validate=True).decode()
            remote = re.search(r'^remote\s+(\S+)\s+(\d+)\s*$', profile, re.M)
            proto = re.search(r'^proto\s+(\S+)\s*$', profile, re.M)
            if not remote or not proto or remote.group(1) != row['IP']:
                continue
            relay = {'ip': row['IP'], 'port': int(remote.group(2)), 'proto': proto.group(1),
                     'country': row['CountryShort'],
                     'score': int(row.get('Score') or 0), 'blocks': {
                         name: re.search('<' + name + r'>(.*?)</' + name + '>', profile, re.S).group(1).strip()
                         for name in ('ca', 'cert', 'key')}}
            candidates.append(validate_relay(relay))
        except (KeyError, ValueError, AttributeError, UnicodeError):
            continue
    unique = {}
    for candidate in sorted(candidates, key=lambda r: r['score'], reverse=True):
        unique.setdefault(candidate['ip'], candidate)
    return list(unique.values())


def load_candidates(*, force=False):
    cache = ROOT / 'candidates.json'
    metadata_path = ROOT / 'catalog.json'
    metadata = read_json(metadata_path, {})
    age = time.time() - metadata.get('fetched_at', 0)
    if not force and metadata.get('version') == 2 and cache.exists() and 0 <= age < CATALOG_REFRESH_SECONDS:
        return [validate_relay(r) for r in read_json(cache, [])]
    try:
        response = run(['curl', '--fail', '--silent', '--show-error', '--connect-timeout', '8', '--max-time', '20',
                        '--max-filesize', '16777216', 'https://www.vpngate.net/api/iphone/'], timeout=25)
        candidates = parse_relays(response.stdout)
        if not candidates:
            raise ValueError('No valid public relays advertised')
        previous = {r['ip'] for r in read_json(cache, [])}
        current = {r['ip'] for r in candidates}
        write_private(cache, json.dumps(candidates))
        metadata = {'version': 2, 'fetched_at': time.time(), 'count': len(candidates),
                    'countries': dict(Counter(r['country'] for r in candidates)),
                    'added': len(current - previous), 'removed': len(previous - current),
                    'sha256': hashlib.sha256(response.stdout.encode()).hexdigest()}
        write_private(metadata_path, json.dumps(metadata))
        print(json.dumps({'catalog_refreshed': metadata}), flush=True)
        return candidates
    except (subprocess.SubprocessError, ValueError):
        # The cache is only a short fallback when the official list is unavailable.
        fetched_at = metadata.get('fetched_at', cache.stat().st_mtime if cache.exists() else 0)
        if cache.exists() and 0 <= time.time() - fetched_at < CATALOG_MAX_AGE_SECONDS:
            return [validate_relay(r) for r in read_json(cache, [])]
        raise


def profile_for(relay):
    validate_relay(relay)
    proto = 'tcp-client' if relay['proto'] == 'tcp' else relay['proto']
    lines = ['client', 'dev tun0', 'proto ' + proto, f"remote {relay['ip']} {relay['port']}",
             'redirect-gateway def1', 'resolv-retry 0', 'connect-retry-max 1', 'connect-timeout 10',
             'tls-timeout 3', 'hand-window 20', 'nobind', 'persist-key', 'persist-tun',
             'remote-cert-tls server', 'verify-x509-name opengw.net name',
             'data-ciphers AES-256-GCM:AES-128-GCM:AES-128-CBC', 'data-ciphers-fallback AES-128-CBC',
             'cipher AES-128-CBC', 'auth SHA1', 'auth-user-pass /run/vpn/auth.txt', 'auth-nocache',
             'auth-retry none', 'script-security 1', 'verb 3', 'log /tmp/openvpn.log',
             'pull-filter ignore "dhcp-option"', 'pull-filter ignore "block-outside-dns"']
    for name in ('ca', 'cert', 'key'):
        lines.append(f"<{name}>\n{relay['blocks'][name].strip()}\n</{name}>")
    return '\n'.join(lines) + '\n'


def owned_container():
    result = run(['docker', 'container', 'inspect', NAME], check=False)
    if result.returncode:
        if 'No such' in result.stderr:
            return None
        raise RuntimeError('Could not inspect VPN container')
    data = json.loads(result.stdout)[0]
    if data['Config'].get('Labels', {}).get(LABEL) != '1':
        raise RuntimeError('Refusing to change a container without the Ppomppu VPN ownership label')
    return data


def remove_owned():
    if owned_container():
        log = run(['docker', 'exec', NAME, 'tail', '-c', '16000', '/tmp/openvpn.log'], check=False).stdout
        write_private(ROOT / 'last-vpn.log', log)
        run(['docker', 'rm', '--force', NAME])


def start_proxy(relay):
    data = owned_container()
    if not data or not data['State']['Running']:
        return False
    if run(['docker', 'exec', NAME, 'pidof', 'tinyproxy'], check=False).returncode == 0:
        return True
    log = run(['docker', 'exec', NAME, 'cat', '/tmp/openvpn.log'], check=False).stdout
    if 'Initialization Sequence Completed' not in log:
        return False
    gateway = data['NetworkSettings']['Networks']['bridge']['Gateway']
    ipaddress.ip_address(gateway)
    conf = f'''Port 8888
Listen 0.0.0.0
Timeout 5
Allow {gateway}
Allow 127.0.0.1
MaxClients 8
ConnectPort 443
Filter "/run/vpn/allowed-domains"
FilterType fnmatch
FilterURLs Off
FilterDefaultDeny Yes
LogLevel Warning
LogFile "/tmp/tinyproxy.log"
PidFile "/tmp/tinyproxy.pid"
'''
    write_private(CONFIG / 'tinyproxy.conf', conf)
    # Only the public proxy configuration needs to be readable by Tinyproxy's user.
    (CONFIG / 'tinyproxy.conf').chmod(0o644)
    (CONFIG / 'allowed-domains').chmod(0o644)
    proto = 'udp' if relay['proto'] == 'udp' else 'tcp'
    rules = [
        ['-F', 'OUTPUT'], ['-A', 'OUTPUT', '-o', 'lo', '-j', 'ACCEPT'],
        ['-A', 'OUTPUT', '-o', 'eth0', '-m', 'conntrack', '--ctstate', 'ESTABLISHED,RELATED', '-j', 'ACCEPT'],
        ['-A', 'OUTPUT', '-o', 'eth0', '-d', relay['ip'], '-p', proto, '--dport', str(relay['port']), '-j', 'ACCEPT'],
        ['-A', 'OUTPUT', '-o', 'tun0', '-p', 'tcp', '--dport', '443', '-j', 'ACCEPT'],
        ['-A', 'OUTPUT', '-o', 'tun0', '-p', 'udp', '--dport', '53', '-j', 'ACCEPT'],
        ['-A', 'OUTPUT', '-o', 'tun0', '-p', 'tcp', '--dport', '53', '-j', 'ACCEPT'],
        ['-P', 'OUTPUT', 'DROP'],
        ['-F', 'INPUT'], ['-A', 'INPUT', '-i', 'lo', '-j', 'ACCEPT'],
        ['-A', 'INPUT', '-m', 'conntrack', '--ctstate', 'ESTABLISHED,RELATED', '-j', 'ACCEPT'],
        ['-A', 'INPUT', '-i', 'eth0', '-s', gateway, '-p', 'tcp', '--dport', '8888', '-j', 'ACCEPT'],
        ['-P', 'INPUT', 'DROP'],
    ]
    for rule in rules:
        run(['docker', 'exec', NAME, 'iptables', *rule], timeout=5)
    run(['docker', 'exec', '--detach', '--user', 'tinyproxy', NAME,
         'tinyproxy', '-d', '-c', '/run/vpn/tinyproxy.conf'])
    return True


def healthy():
    LAST_PROBE.clear()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({'https': PROXY}))
    request = urllib.request.Request(URL, headers={
        'User-Agent': UA, 'Accept': '*/*', 'Accept-Encoding': 'gzip, deflate',
        'Accept-Language': 'ko,en-US;q=0.9,en;q=0.8'})
    try:
        with opener.open(request, timeout=15) as response:
            body = response.read(524288)
            encoding = response.headers.get('Content-Encoding', '').lower()
            if encoding == 'gzip':
                with gzip.GzipFile(fileobj=io.BytesIO(body)) as compressed:
                    body = compressed.read(524288)
            elif encoding == 'deflate':
                body = zlib.decompressobj().decompress(body, 524288)
            LAST_PROBE.update(status=response.status, bytes=len(body), list_found=b'bbs_new1' in body)
            return response.status == 200 and b'bbs_new1' in body and b'<title>403 Forbidden' not in body
    except (OSError, urllib.error.URLError, EOFError, zlib.error) as error:
        LAST_PROBE.update(error=type(error).__name__, reason=str(error)[:200])
        return False


def host_addresses():
    # Resolve public target names on the host; volunteer relays often have broken DNS.
    # HTTPS still uses the original name and validates its certificate end to end.
    arguments = []
    for domain in DOMAINS:
        result = run(['getent', 'ahostsv4', domain], timeout=8)
        addresses = list(dict.fromkeys(line.split()[0] for line in result.stdout.splitlines() if line.strip()))
        if not addresses or any(not ipaddress.IPv4Address(a).is_global for a in addresses):
            raise ValueError('Ppomppu DNS did not return public IPv4 addresses')
        for address in addresses:
            arguments.extend(['--add-host', domain + ':' + address])
    return arguments


def available_candidates(candidates, state, now):
    eligible = [r for r in candidates if state.get('failed_until', {}).get(r['ip'], 0) <= now
                and state.get('failed_prefix_until', {}).get(
                    str(ipaddress.ip_network(r['ip'] + '/24', strict=False)), 0) <= now]
    history = state.get('attempt_history', {})
    untried = [r for r in eligible if r['ip'] not in history]
    pool = sorted(untried or eligible, key=lambda r: (
        history.get(r['ip'], {}).get('at', 0),
        {'KR': 0, 'JP': 1}.get(r.get('country', 'KR'), 2), -r.get('score', 0), r['ip']))
    selected, prefixes, countries = [], set(), set()
    # Visit the entire list before revisiting failed, high-score endpoints.
    for diversify_countries in (True, False):
        for relay in pool:
            prefix = str(ipaddress.ip_network(relay['ip'] + '/24', strict=False))
            country = relay.get('country', 'KR')
            if prefix in prefixes or (diversify_countries and country in countries):
                continue
            selected.append(relay)
            prefixes.add(prefix)
            countries.add(country)
            if len(selected) == 3:
                return selected
    return selected


def record_failure(state, relay):
    state['failed_until'][relay['ip']] = time.time() + 3600
    entry = state.setdefault('attempt_history', {}).setdefault(relay['ip'], {'at': time.time(), 'count': 1})
    entry['outcome'] = LAST_PROBE.get('error', 'invalid_list')
    if LAST_PROBE.get('error') == 'HTTPError' and '403' in LAST_PROBE.get('reason', ''):
        prefix = str(ipaddress.ip_network(relay['ip'] + '/24', strict=False))
        state['failed_prefix_until'][prefix] = time.time() + 3600


def create(relay):
    LAST_PROBE.clear()
    addresses = host_addresses()
    remove_owned()
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 18888))
    write_private(CONFIG / 'client.ovpn', profile_for(relay))
    write_private(CONFIG / 'auth.txt', 'vpn\nvpn\n')
    write_private(CONFIG / 'allowed-domains', 'www.ppomppu.co.kr\nm.ppomppu.co.kr\n')
    run(['docker', 'run', '--detach', '--name', NAME, '--label', LABEL + '=1', '--init',
         '--restart', 'unless-stopped', '--network', 'bridge', '--dns', '1.1.1.1', '--dns', '8.8.8.8',
         '--cap-drop', 'ALL', '--cap-add', 'NET_ADMIN', '--cap-add', 'NET_RAW', '--device', '/dev/net/tun',
         '--security-opt', 'no-new-privileges:true', '--read-only', '--sysctl', 'net.ipv6.conf.all.disable_ipv6=1',
         '--tmpfs', '/tmp:rw,nosuid,nodev,noexec,size=32m,mode=1777', '--cpus', '0.15', '--memory', '128m',
         '--pids-limit', '64', '--log-driver', 'local', '--log-opt', 'max-size=2m', '--log-opt', 'max-file=3',
         '--publish', '127.0.0.1:18888:8888', '--volume', str(CONFIG) + ':/run/vpn:ro', *addresses, IMAGE])
    deadline = time.monotonic() + 35
    while time.monotonic() < deadline:
        if start_proxy(relay):
            # Give the small proxy process a moment to bind its listening port.
            time.sleep(1)
            return healthy()
        time.sleep(2)
    LAST_PROBE.update(error='VPNInitializationTimeout')
    return False


def main():
    os.umask(0o077)
    ROOT.mkdir(mode=0o700, exist_ok=True)
    CONFIG.mkdir(mode=0o755, exist_ok=True)
    CONFIG.chmod(0o755)
    with (ROOT / 'guard.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        path = ROOT / 'state.json'
        state = read_json(path, {})
        if state.get('probe_version') != 2:
            # The old identity-encoding probe rejected usable relays; discard its exclusions.
            state.update(probe_version=2, failed_until={}, failed_prefix_until={}, failures=0, retry_after=0)
        history = state.setdefault('attempt_history', {})
        for ip, until in state.get('failed_until', {}).items():
            history.setdefault(ip, {'at': until - 3600, 'count': 1, 'outcome': 'previous_failure'})
        state['attempt_history'] = {ip: entry for ip, entry in history.items()
                                    if entry.get('at', 0) > time.time() - 30 * 86400}
        state['failed_until'] = {ip: until for ip, until in state.get('failed_until', {}).items()
                                 if until > time.time()}
        state['failed_prefix_until'] = {prefix: until for prefix, until in state.get('failed_prefix_until', {}).items()
                                        if until > time.time()}
        try:
            catalog = load_candidates()
        except (subprocess.SubprocessError, OSError, ValueError):
            catalog = None
        current = owned_container()
        relay = state.get('relay')
        if current and current['State']['Running'] and relay:
            start_proxy(relay)
            if healthy():
                state.update(healthy_at=time.time(), failures=0, retry_after=0)
                write_private(path, json.dumps(state))
                print(json.dumps({'healthy': True, 'relay_ip': relay['ip']}), flush=True)
                return
            state['failures'] = state.get('failures', 0) + 1
            if state['failures'] < 2:
                write_private(path, json.dumps(state))
                print('Ppomppu proxy probe failed once; checking again next minute', flush=True)
                return
        if relay and current:
            record_failure(state, relay)
        if time.time() < state.get('retry_after', 0):
            write_private(path, json.dumps(state))
            return
        if catalog is None:
            remove_owned()
            state['retry_after'] = time.time() + 600
            write_private(path, json.dumps(state))
            print('Official relay list unavailable; cooling down for 600 seconds', flush=True)
            return
        candidates = available_candidates(catalog, state, time.time())
        for candidate in candidates:
            if not available_candidates([candidate], state, time.time()):
                continue
            state['relay'] = {k: candidate[k] for k in ('ip', 'port', 'proto', 'country') if k in candidate}
            previous_attempt = state['attempt_history'].get(candidate['ip'], {})
            state['attempt_history'][candidate['ip']] = {'at': time.time(),
                'count': previous_attempt.get('count', 0) + 1, 'outcome': 'checking'}
            write_private(path, json.dumps(state))
            try:
                recovered = create(candidate)
            except (subprocess.SubprocessError, OSError, ValueError) as error:
                recovered = False
                LAST_PROBE.update(error=type(error).__name__)
            if recovered:
                state.update(healthy_at=time.time(), failures=0, retry_after=0)
                state['attempt_history'][candidate['ip']]['outcome'] = 'healthy'
                write_private(path, json.dumps(state))
                print(json.dumps({'recovered': True, 'relay_ip': candidate['ip']}), flush=True)
                return
            record_failure(state, candidate)
            write_private(path, json.dumps(state))
            print(json.dumps({'relay_failed': candidate['ip'], 'retry_in_seconds': 3600,
                              'probe': LAST_PROBE}), flush=True)
        remove_owned()
        remaining = available_candidates(catalog, state, time.time())
        delay = 60 if any(r['ip'] not in state['attempt_history'] for r in remaining) else 600
        state.update(failures=0, retry_after=time.time() + delay)
        write_private(path, json.dumps(state))
        print(f'No working relay in this cycle; cooling down for {delay} seconds', flush=True)


if __name__ == '__main__':
    main()
