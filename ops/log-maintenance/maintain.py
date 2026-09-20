#!/usr/bin/env python3
"""Crawler log retention; defaults to inspection. Never removes Docker files."""
import argparse
import json
import os
import socket
import subprocess


def run(args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=30).stdout.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='rotate/vacuum according to installed retention policy')
    args = parser.parse_args()
    if socket.gethostname() != 'instance-20251207-1802' or os.geteuid() != 0:
        raise RuntimeError('Run as root on the crawler host')
    before = os.statvfs('/')
    if args.apply:
        run(['logrotate', '--state', '/var/lib/geteverything-log-maintenance/logrotate.status',
             '/etc/geteverything-log-maintenance/logrotate.conf'])
        run(['journalctl', '--vacuum-size=200M', '--vacuum-time=14d'])
    else:
        run(['logrotate', '--debug', '--state', '/var/lib/geteverything-log-maintenance/logrotate.status',
             '/etc/geteverything-log-maintenance/logrotate.conf'])
    after = os.statvfs('/')
    print(json.dumps({'action': 'retention_applied' if args.apply else 'dry_run',
                      'available_bytes': after.f_bavail * after.f_frsize,
                      'reclaimed_bytes': (after.f_bavail - before.f_bavail) * after.f_frsize,
                      'journal': run(['journalctl', '--disk-usage'])}))


if __name__ == '__main__':
    main()
