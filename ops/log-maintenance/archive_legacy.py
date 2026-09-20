#!/usr/bin/env python3
"""One-time archival of the known stopped recovery container, using Docker APIs."""
import argparse
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import time

NAME = 'crawlers-bot-before-recovery-20260913'
EXPECTED_ID = 'f1ceaf4e0265ac00d1ce6ce2bb1402c9c26be6ed6abe4d48eeca3cb35f341661'
ARCHIVE = Path('/var/backups/geteverything-logs/legacy-20260915')


def run(*args, timeout=60):
    return subprocess.check_output(args, timeout=timeout).decode().strip()


def inspect(name):
    return json.loads(run('docker', 'inspect', name))[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    old = inspect(NAME)
    if old['Id'] != EXPECTED_ID or old['State']['Running'] or old['State']['Paused']:
        raise RuntimeError('Expected stopped legacy container is absent; no changes made')
    if old['HostConfig']['NetworkMode'] != 'host' or any(m['Type'] != 'bind' for m in old['Mounts']):
        raise RuntimeError('Unexpected mounts or networking; no changes made')
    path = Path(old['LogPath'])
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_mtime > time.time() - 7 * 86400:
        raise RuntimeError('Legacy log is not an old regular file')
    free = os.statvfs(ARCHIVE.parent if ARCHIVE.parent.exists() else '/var/backups')
    if free.f_bavail * free.f_frsize < before.st_size + 2 * 1024**3:
        raise RuntimeError('Insufficient space to archive safely')
    print(json.dumps({'phase': 'plan', 'container': NAME, 'bytes': before.st_size, 'apply': args.apply}), flush=True)
    if not args.apply:
        return
    os.umask(0o077)
    ARCHIVE.mkdir(parents=True, exist_ok=False, mode=0o700)
    (ARCHIVE / 'inspect.json').write_text(json.dumps(old))
    digest = hashlib.sha256()
    total = 0
    # Read an immutable, stopped container log; never truncate Docker-managed files.
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as src:
        with gzip.open(ARCHIVE / 'docker-json.log.gz', 'wb', compresslevel=1) as dst:
            while chunk := src.read(1024 * 1024):
                digest.update(chunk)
                total += len(chunk)
                dst.write(chunk)
    after = path.lstat()
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        raise RuntimeError('Log changed during archival; container preserved')
    verified, count = hashlib.sha256(), 0
    with gzip.open(ARCHIVE / 'docker-json.log.gz', 'rb') as src:
        while chunk := src.read(1024 * 1024):
            verified.update(chunk)
            count += len(chunk)
    if count != total or verified.digest() != digest.digest():
        raise RuntimeError('Archive verification failed; container preserved')
    print(json.dumps({'phase': 'archive_verified', 'bytes': total}), flush=True)
    image = run('docker', 'commit', EXPECTED_ID, 'crawler-rollback:before-recovery-20260915', timeout=180)
    config = copy.deepcopy(old['Config'])
    config['Image'] = image
    config['HostConfig'] = copy.deepcopy(old['HostConfig'])
    config['HostConfig']['LogConfig'] = {'Type': 'local', 'Config': {'max-size': '20m', 'max-file': '5'}}
    (ARCHIVE / 'create.json').write_text(json.dumps(config))
    if inspect(NAME)['State']['Running']:
        raise RuntimeError('Legacy container started; refusing replacement')
    run('docker', 'rename', EXPECTED_ID, NAME + '-archived')
    try:
        result = json.loads(run('curl', '--fail', '--silent', '--show-error', '--max-time', '30',
                                '--unix-socket', '/var/run/docker.sock', '-H', 'Content-Type: application/json',
                                '--data-binary', '@' + str(ARCHIVE / 'create.json'),
                                'http://localhost/containers/create?name=' + NAME))
        replacement = inspect(result['Id'])
        if replacement['State']['Running'] or replacement['Mounts'] != old['Mounts']:
            raise RuntimeError('Replacement validation failed; archived container preserved')
    except Exception:
        # If create succeeded but validation failed, retain both for inspection.
        if not run('docker', 'ps', '-aq', '--filter', 'name=^/' + NAME + '$'):
            run('docker', 'rename', EXPECTED_ID, NAME)
        raise
    # Docker rejects removal if it became running. Do not pass --force or --volumes.
    run('docker', 'rm', EXPECTED_ID)
    (ARCHIVE / 'result.json').write_text(json.dumps({
        'source_bytes': total, 'archive_bytes': (ARCHIVE / 'docker-json.log.gz').stat().st_size,
        'sha256': digest.hexdigest(), 'rollback_image': image, 'replacement_id': replacement['Id'],
        'completed_at': time.time(),
    }, indent=2))
    print((ARCHIVE / 'result.json').read_text(), flush=True)


if __name__ == '__main__':
    main()
