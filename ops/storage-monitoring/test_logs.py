import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

import logs
import export


class LogCollectorTests(unittest.TestCase):
    def test_caps_output_and_reaps_writer(self):
        raw, truncated, code = logs.bounded_command(
            [sys.executable, '-c', 'import os\nwhile True: os.write(1,b"x"*8192)'], limit=1024)
        self.assertEqual(len(raw), 1024)
        self.assertTrue(truncated)
        self.assertIsNone(code)

    def test_hanging_parent_and_inherited_pipe_are_timed_out(self):
        for script in ('import time; time.sleep(10)',
                       'import subprocess,sys; subprocess.Popen([sys.executable,"-c","import time; time.sleep(10)"])'):
            start = time.monotonic()
            with self.assertRaises(subprocess.TimeoutExpired):
                logs.bounded_command([sys.executable, '-c', script], timeout=.2)
            self.assertLess(time.monotonic() - start, 2)

    def test_masks_secrets_control_codes_and_bounds_long_lines(self):
        raw = (b'\x1b[31mERROR ok\x1b[0m\x00\n'
               b'Authorization: Bearer abc-secret\nCookie: sessionid=secret-cookie\n'
               b'{"DATABASE_PASSWORD": "db-secret", "token": "token-secret"}\n'
               b'postgres://alice:dsn-secret@db/getev\n'
               b'eyJabc.eyJdef.signature\nBearer loose-secret\n'
               b'-----BEGIN PRIVATE KEY-----\nprivate-body\n-----END PRIVATE KEY-----\n' + b'x'*9000)
        lines = logs.redact(raw)
        text = '\n'.join(lines)
        for secret in ('abc-secret', 'secret-cookie', 'db-secret', 'token-secret', 'dsn-secret',
                       'private-body', 'eyJabc', 'loose-secret', '\x1b', '\x00'):
            self.assertNotIn(secret, text)
        self.assertIn('ERROR ok', text)
        self.assertTrue(all(len(line) < 2100 for line in lines))
        self.assertEqual(len(logs.redact(b'line\n'*1000)), 300)

    def test_collection_failure_preserves_last_lines_and_time(self):
        with TemporaryDirectory() as directory:
            with patch('logs.bounded_command', return_value=(b'INFO saved\n', False, 0)):
                logs.collect(directory)
            before = json.loads((Path(directory) / 'logs.json').read_text())
            with patch('logs.bounded_command', side_effect=subprocess.TimeoutExpired('docker', 3)):
                logs.collect(directory)
            after = json.loads((Path(directory) / 'logs.json').read_text())
            self.assertEqual(before['sources'][0]['lines'], after['sources'][0]['lines'])
            self.assertEqual(before['sources'][0]['measured_at'], after['sources'][0]['measured_at'])
            self.assertTrue(after['sources'][0]['error'])

    def test_failed_log_transfer_preserves_snapshot_and_enforces_fixed_command(self):
        with TemporaryDirectory() as directory:
            (Path(directory) / 'snapshots').mkdir()
            path = Path(directory) / 'snapshots/crawler-logs.json'
            old = {'report': {'measured_at': 12}, 'received_at': 14}
            path.write_text(json.dumps(old))
            config = {'state_directory': directory, 'identity_file': '/key', 'known_hosts_file': '/hosts'}
            with patch('logs.bounded_command', return_value=(b'x'*100, True, None)) as command:
                logs.pull(config, {'target': 'ubuntu@crawler'})
            self.assertEqual(json.loads(path.read_text())['report'], old['report'])
            self.assertEqual(command.call_args.args[0][-1], 'logs')
            self.assertEqual(command.call_args.kwargs['limit'], logs.MAX_REPORT_BYTES)

    def test_export_rejects_arbitrary_commands_without_reading_files(self):
        for command in ('cat /etc/shadow', 'logs; id', '../logs', 'logs\n', 'report.json'):
            with patch.dict('os.environ', {'SSH_ORIGINAL_COMMAND': command}), patch('pathlib.Path.open') as read:
                self.assertEqual(export.main(), 1)
                read.assert_not_called()


if __name__ == '__main__':
    unittest.main()
