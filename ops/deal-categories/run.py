#!/usr/bin/env python3
"""Launch an isolated category worker; credentials remain in a root-only file."""
import fcntl
import json
from pathlib import Path
import subprocess


def main():
    config = json.loads(Path('/etc/geteverything-categories/runtime.json').read_text())
    with Path('/run/geteverything-categories.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        command = ['docker', 'run', '--rm', '--name', 'geteverything-category-worker', '--init', '--network=host',
                   '--read-only', '--user=65534:65534', '--cap-drop=ALL', '--security-opt=no-new-privileges',
                   '--memory=192m', '--memory-swap=192m', '--cpus=0.15', '--cpu-shares=128', '--pids-limit=64',
                   '--tmpfs=/tmp:rw,nosuid,nodev,size=16m', '--log-driver=local', '--log-opt=max-size=2m', '--log-opt=max-file=2',
                   '--env-file=/etc/geteverything-categories/worker.env',
                   '--mount=type=bind,src=/var/lib/geteverything-categories/state,dst=/state',
                   config['worker_image'], 'python', '-m', 'gadmin.categories.worker']
        try:
            subprocess.run(command, check=True)
        finally:
            subprocess.run(['docker', 'stop', '--time', '250', 'geteverything-category-worker'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=260)


if __name__ == '__main__':
    main()
