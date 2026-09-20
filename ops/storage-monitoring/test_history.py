from contextlib import closing
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import history


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'history.sqlite3'
        self.db = history.connect(self.path)
        self.addCleanup(self.db.close)
        self.now = history.timestamp_us('2026-09-16T06:00:00Z')

    def test_incremental_overlap_deduplicates_without_losing_equal_timestamp_events(self):
        line = b'2026-09-16T05:59:59.123456789Z INFO same\n'
        with patch('history.bounded_command', return_value=(line*2, False, 0)):
            history.collect_source(self.db, 'crawler', self.now)
            history.collect_source(self.db, 'crawler', self.now)
        self.assertEqual(self.db.execute('SELECT count(*) FROM events').fetchone()[0], 2)

    def test_truncated_partial_record_retried_and_cursor_advances_only_to_complete_record(self):
        line = b'2026-09-16T05:59:50.000000000Z INFO first\n'
        with patch('history.bounded_command', return_value=(line + b'2026-09-16T05:59:51.00000', True, None)):
            self.assertTrue(history.collect_source(self.db, 'crawler', self.now))
        self.assertEqual(history.meta(self.db, 'source:crawler')['cursor'], self.now-10000000)
        with patch('history.bounded_command', return_value=(line + b'2026-09-16T05:59:51Z ERROR next\n', False, 0)):
            self.assertFalse(history.collect_source(self.db, 'crawler', self.now))
        self.assertEqual(self.db.execute('SELECT count(*) FROM events').fetchone()[0], 2)

    def test_secrets_are_masked_before_persistence_including_split_private_key(self):
        first = b'2026-09-16T05:59:49Z PASSWORD=super-secret\n2026-09-16T05:59:50Z -----BEGIN PRIVATE KEY-----\n'
        second = b'2026-09-16T05:59:51Z private-body\n2026-09-16T05:59:52Z -----END PRIVATE KEY-----\n'
        with patch('history.bounded_command', return_value=(first, True, None)):
            history.collect_source(self.db, 'crawler', self.now)
        with patch('history.bounded_command', return_value=(second, False, 0)):
            history.collect_source(self.db, 'crawler', self.now)
        stored = ' '.join(row[0] for row in self.db.execute('SELECT text FROM events'))
        self.assertNotIn('super-secret', stored)
        self.assertNotIn('private-body', stored)
        self.assertIn('REDACTED', stored)

    def test_giant_record_is_omitted_before_regex_processing(self):
        raw = b'2026-09-16T05:59:59Z ' + b'secret-body'*50000
        ts, message, identity = history.parse_line('crawler', raw)
        self.assertEqual(message, '[긴 로그 항목 생략]')
        self.assertLess(len(identity), 128)

    def test_export_size_and_cursor_are_bounded_and_continue_in_order(self):
        self.db.executemany('INSERT INTO events(source,ts,severity,text) VALUES (?,?,?,?)',
                            [('crawler', self.now, 'info', '한'*2000)] * 600)
        self.db.commit()
        page = history.export_page(self.path, 0)
        self.assertLess(len(json.dumps(page, ensure_ascii=False).encode()), history.TRANSFER_BYTES)
        self.assertTrue(page['has_more'])
        following = history.export_page(self.path, page['next_id'])
        self.assertGreater(following['rows'][0][0], page['next_id'])

    def test_retention_removes_expired_events_and_reserves_capacity(self):
        self.db.execute('INSERT INTO events(source,ts,severity,text) VALUES (?,?,?,?)',
                        ('crawler', self.now-history.RETENTION_US-1, 'info', 'old'))
        self.db.execute('INSERT INTO events(source,ts,severity,text) VALUES (?,?,?,?)',
                        ('crawler', self.now, 'info', 'new'))
        self.db.commit()
        history.retain(self.db, self.now)
        self.assertEqual(self.db.execute('SELECT text FROM events').fetchall(), [('new',)])
        self.assertEqual(self.db.execute('PRAGMA max_page_count').fetchone()[0], history.MAX_PAGES)

    def test_transfer_rejects_unordered_oversized_or_wrong_source_rows(self):
        page = history.export_page(self.path, 0)
        for row in ([1, 'other', self.now, 'info', 'x'], [0, 'crawler', self.now, 'info', 'x'],
                    [1, 'crawler', self.now, 'info', 'x'*2101]):
            page.update(rows=[row], next_id=row[0])
            with self.assertRaises(ValueError):
                history.validate_page(page, 0)


if __name__ == '__main__':
    unittest.main()
