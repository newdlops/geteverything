import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import collect


class CollectorTests(unittest.TestCase):
    def test_available_space_excludes_reserved_blocks(self):
        stat = SimpleNamespace(f_blocks=100, f_bfree=30, f_bavail=20, f_frsize=4096,
                               f_files=200, f_favail=80)
        with patch('collect.os.statvfs', return_value=stat):
            value = collect.filesystem('/tmp', 'disk')
        self.assertEqual(value['used_bytes'], 70*4096)
        self.assertEqual(value['available_bytes'], 20*4096)
        self.assertEqual(value['reserved_bytes'], 10*4096)

    def test_shared_paths_are_measured_once_per_device(self):
        with TemporaryDirectory() as directory:
            errors = []
            volumes = collect.disk_volumes([('one', directory), ('two', directory)], errors)
            self.assertEqual(len(volumes), 1)
            self.assertEqual(errors, [])

    def test_du_is_bounded_and_counts_allocated_bytes(self):
        with patch('collect.run', return_value='4096\t/log/a\n8192\t/log/b\n') as run:
            self.assertEqual(collect.allocated_size(['/log/a', '/log/b']), 12288)
            self.assertEqual(run.call_args.kwargs['timeout'], 10)
            self.assertIn('-x', run.call_args.args[0])
        self.assertEqual(collect.allocated_size([]), 0)

    def test_database_query_is_read_only_with_statement_timeout(self):
        report = {'errors': []}
        response = json.dumps({'database_bytes': 456, 'data_directory': '/data', 'tablespaces': []})
        with patch('collect.run', return_value=response) as run, patch('collect.disk_volumes', return_value=[]):
            collect.database({'database_name': 'getev', 'data_directory': '/data'}, report)
        self.assertEqual(report['sizes'][0]['bytes'], 456)
        self.assertIn('default_transaction_read_only=on', run.call_args.kwargs['env']['PGOPTIONS'])
        self.assertIn('statement_timeout=5000', run.call_args.kwargs['env']['PGOPTIONS'])

    def test_failed_pull_preserves_last_snapshot_and_uses_restricted_ssh(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'snapshots'
            path.mkdir()
            target = path / 'database.json'
            old = {'report': {'measured_at': 123}, 'received_at': 125, 'error': None}
            target.write_text(json.dumps(old))
            config = {'state_directory': directory, 'identity_file': '/key', 'known_hosts_file': '/hosts'}
            with patch('collect.run', side_effect=subprocess.TimeoutExpired('ssh', 12)) as run:
                collect.pull(config, {'source': 'database', 'target': 'ubuntu@db'})
            current = json.loads(target.read_text())
            self.assertEqual(current['report'], old['report'])
            self.assertEqual(current['received_at'], 125)
            self.assertTrue(current['error'])
            self.assertIn('StrictHostKeyChecking=yes', run.call_args.args[0])
            self.assertIn('ConnectionAttempts=1', run.call_args.args[0])
            self.assertEqual(run.call_args.kwargs['timeout'], 12)

    def test_pull_rejects_other_source_and_future_measurement(self):
        with TemporaryDirectory() as directory:
            (Path(directory) / 'snapshots').mkdir()
            config = {'state_directory': directory, 'identity_file': '/key', 'known_hosts_file': '/hosts'}
            for source, timestamp in (('crawler', 50), ('database', 1000)):
                with patch('collect.time.time', return_value=100), patch('collect.run', return_value=json.dumps({
                        'source': source, 'version': 1, 'measured_at': timestamp})):
                    collect.pull(config, {'source': 'database', 'target': 'ubuntu@db'})
                self.assertTrue(json.loads((Path(directory) / 'snapshots/database.json').read_text())['error'])


if __name__ == '__main__':
    unittest.main()
