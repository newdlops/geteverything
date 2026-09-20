#!/usr/bin/env python3
"""Use the running web image, with a separate memory/CPU limit and persistent files."""
import fcntl
import json
from pathlib import Path
import subprocess
import sys
import sqlite3


def main():
    arguments = sys.argv[1:]
    if any(value not in ('--start-backfill', '--status', '--watch') for value in arguments):
        raise SystemExit('Only --start-backfill, --status and --watch are supported')
    if '--status' in arguments:
        with sqlite3.connect('file:/var/lib/geteverything-thumbnails/queue.sqlite3?mode=ro', uri=True, timeout=2) as database:
            status = {key: json.loads(value) for key, value in database.execute('SELECT key,value FROM metadata')}
            status['queue'] = {state: count for state, count in database.execute('SELECT status,count(*) FROM jobs GROUP BY status')}
        print(json.dumps(status))
        return
    with Path('/run/geteverything-product-thumbnails.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({'worker_busy': True}))
            return
        service = json.loads(subprocess.check_output(
            ['docker', 'service', 'inspect', 'django_django'], timeout=10))[0]
        image = service['Spec']['TaskTemplate']['ContainerSpec']['Image']
        command = ['docker', 'run', '--rm', '--name', 'geteverything-thumbnail-worker',
                   '--init', '--read-only', '--user', '65534:65534', '--cap-drop=ALL',
                   '--security-opt=no-new-privileges', '--pids-limit=64',
                   '--memory=192m', '--memory-swap=192m', '--cpus=0.25',
                   '--tmpfs', '/tmp:rw,nosuid,nodev,size=16m',
                   '--log-driver=local', '--log-opt=max-size=2m', '--log-opt=max-file=2',
                   '--env-file', '/etc/geteverything-thumbnails/worker.env',
                   '--mount', 'type=bind,src=/var/lib/geteverything-thumbnails,dst=/var/lib/geteverything-thumbnails',
                   image, 'python', '-m', 'gadmin.thumbnails.worker', *arguments]
        try:
            subprocess.run(command, timeout=None if '--watch' in arguments else 115, check=True)
        finally:
            # Only this dedicated, disposable worker is eligible for cleanup.
            subprocess.run(['docker', 'stop', '--time', '50', 'geteverything-thumbnail-worker'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=55)


if __name__ == '__main__':
    main()
