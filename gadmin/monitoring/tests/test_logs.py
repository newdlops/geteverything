from datetime import timedelta
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from gadmin.monitoring.logs import log_context, KST, SOURCES, MAX_DATABASE_BYTES


class LogViewerTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        override = override_settings(STORAGE_METRICS_DIR=directory.name)
        override.enable()
        self.addCleanup(override.disable)
        self.path = Path(directory.name) / 'log-history.sqlite3'
        self.db = sqlite3.connect(self.path)
        self.addCleanup(self.db.close)
        self.db.executescript('''CREATE TABLE events(id INTEGER PRIMARY KEY AUTOINCREMENT,source TEXT,ts INTEGER,severity TEXT,text TEXT);
          CREATE INDEX events_source_time ON events(source,ts DESC,id DESC);
          CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);''')
        self.now = timezone.now().astimezone(KST).replace(microsecond=0)
        self.us = int(self.now.timestamp()*1000000)
        self.params = {'start': (self.now-timedelta(hours=1)).isoformat()[:19], 'end': self.now.isoformat()[:19]}
        self.set_meta('generation', 'a'*32)
        self.set_meta('received_at', self.now.timestamp())
        for source, _ in SOURCES:
            self.set_meta('source:'+source, {'checked_at': self.now.timestamp()})
            self.add('INFO PPOMPPU saved', source=source)

    def set_meta(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', (key,json.dumps(value)))
        self.db.commit()

    def add(self, text, source='crawler', ts=None, severity='info'):
        self.db.execute('INSERT INTO events(source,ts,severity,text) VALUES (?,?,?,?)',
                        (source, ts if ts is not None else self.us-1000000, severity,text))
        self.db.commit()

    def login(self, superuser=True):
        user = get_user_model().objects.create_user('operator',is_staff=True,is_superuser=superuser)
        self.client.force_login(user)
        return user

    def test_superuser_only_on_page_and_data_and_read_only_method(self):
        for route in ('/admin/logs/','/admin/logs/data/'):
            self.assertEqual(self.client.get(route).status_code,302)
        user = self.login(False)
        self.assertNotContains(self.client.get('/admin/'),'/admin/logs/')
        for route in ('/admin/logs/','/admin/logs/data/'):
            self.assertEqual(self.client.get(route).status_code,403)
        user.is_superuser = True
        user.save()
        self.assertContains(self.client.get('/admin/'),'/admin/logs/')
        self.assertContains(self.client.get('/admin/logs/',self.params),'PPOMPPU saved')
        self.assertIn('no-store',self.client.get('/admin/logs/data/',self.params).headers['Cache-Control'])
        self.assertEqual(self.client.post('/admin/logs/data/').status_code,405)

    def test_pagination_is_stable_for_equal_timestamps_and_concurrent_arrivals(self):
        for index in range(650):
            self.add('row '+str(index))
        params = dict(self.params)
        seen = []
        first = True
        while True:
            result = log_context(params)
            self.assertEqual(result['http_status'],200)
            self.assertLessEqual(len(result['lines']),200)
            seen += [line['id'] for line in result['lines']]
            if first:
                self.add('arrived later with old timestamp')
                first = False
            if not result['next_cursor']:
                break
            params['cursor'] = result['next_cursor']
        self.assertEqual(len(seen),651)
        self.assertEqual(len(set(seen)),651)
        self.assertEqual(seen,sorted(seen,reverse=True))

    def test_kst_range_includes_last_second_and_excludes_outside(self):
        self.add('within last second',ts=self.us+999999)
        self.add('outside',ts=self.us+1000000)
        result = log_context({**self.params,'start':self.now.isoformat()[:19]})
        self.assertEqual([line['text'] for line in result['lines']],['within last second'])
        self.assertEqual(result['lines'][0]['time'].utcoffset(),timedelta(hours=9))

    def test_literal_search_does_not_interpret_sql_wildcards(self):
        self.add('ERROR 100% [x]',severity='error')
        self.add('WARNING 100 dollars',severity='warning')
        result = log_context({**self.params,'q':'100% [x]','level':'attention'})
        self.assertEqual([line['text'] for line in result['lines']],['ERROR 100% [x]'])
        self.assertEqual(log_context({**self.params,'q':"' OR 1=1 --"})['lines'],[])

    def test_exact_seven_day_range_is_allowed(self):
        result = log_context({**self.params, 'start': (self.now-timedelta(days=7)).isoformat()[:19]})
        self.assertEqual(result['http_status'], 200)

    def test_reversed_invalid_or_excessive_range_rejected_before_database(self):
        for extra in ({'start':'invalid'}, {'start':''}, {'start':self.now.isoformat()[:19], 'end':self.params['start']},
                      {'start':(self.now-timedelta(days=8)).isoformat()[:19]}):
            with patch('gadmin.monitoring.logs.sqlite3.connect') as connection:
                result = log_context({**self.params,**extra})
                self.assertEqual(result['http_status'],400)
                connection.assert_not_called()

    def test_cursor_tampering_filter_changes_and_generation_change_rejected(self):
        for index in range(210):
            self.add(str(index))
        cursor = log_context(self.params)['next_cursor']
        for extra in ({'cursor':cursor+'x'}, {'cursor':cursor,'q':'different'}):
            self.assertEqual(log_context({**self.params,**extra})['http_status'],400)
        self.set_meta('generation','b'*32)
        self.assertEqual(log_context({**self.params,'cursor':cursor})['http_status'],400)

    def test_stale_or_failed_sync_keeps_queryable_history(self):
        self.set_meta('received_at',self.now.timestamp()-400)
        self.assertEqual(log_context(self.params)['state'],'stale')
        self.set_meta('error','transport failed')
        result = log_context(self.params)
        self.assertEqual(result['state'],'error')
        self.assertEqual(len(result['lines']),1)

    def test_html_escaped_in_full_page_and_ajax(self):
        self.add('<script>alert(1)</script>')
        self.login()
        self.assertContains(self.client.get('/admin/logs/',self.params),'&lt;script&gt;')
        response = self.client.get('/admin/logs/data/',self.params).json()
        self.assertNotIn('<script>alert',response['html'])
        self.assertIn('&lt;script&gt;',response['html'])

    def test_missing_corrupt_and_oversized_database_return_visible_states(self):
        self.db.close()
        self.path.unlink()
        self.assertEqual(log_context(self.params)['state'],'pending')
        self.path.write_bytes(b'not sqlite')
        self.assertEqual(log_context(self.params)['http_status'],503)
        with self.path.open('wb') as stream:
            stream.truncate(MAX_DATABASE_BYTES+1)
        self.assertEqual(log_context(self.params)['http_status'],503)

    def test_empty_result_and_retention_boundary_are_explicit(self):
        result = log_context({**self.params,'q':'missing'})
        self.assertEqual(result['lines'],[])
        self.assertEqual(result['state'],'healthy')
        self.assertTrue(result['outside_retention'])
        self.assertIsNotNone(result['available_from'])

    def test_ajax_date_error_explains_field(self):
        self.login()
        response = self.client.get('/admin/logs/data/',{**self.params,'end':self.params['start']})
        self.assertEqual(response.status_code,200)
        response = self.client.get('/admin/logs/data/',{**self.params,'start':'invalid'})
        self.assertEqual(response.status_code,400)
        self.assertEqual(response.json()['error_field'],'start')
