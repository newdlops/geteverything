import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from gadmin.monitoring.storage import MAX_SNAPSHOT_BYTES, source_context


def snapshot(now, source='database'):
    return {'received_at': now.timestamp(), 'error': None, 'report': {
        'version': 1, 'source': source, 'hostname': 'database-host',
        'measured_at': now.timestamp(), 'errors': [],
        'sizes': [{'label': 'getev DB 데이터', 'bytes': 123456789}],
        'volumes': [{'label': 'DB 데이터 디스크', 'path': '/var/lib/postgresql/16/main',
                     'total_bytes': 1000, 'used_bytes': 150, 'available_bytes': 800,
                     'reserved_bytes': 50, 'inode_total': 100, 'inode_available': 90}],
    }}


class StorageTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings_override = override_settings(STORAGE_METRICS_DIR=self.temp.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.now = timezone.now()
        self.payload = snapshot(self.now)

    def save(self):
        (Path(self.temp.name) / 'database.json').write_text(json.dumps(self.payload))

    def result(self):
        return source_context('database', 'DB 서버', 'shared', self.now)

    def staff(self):
        user = get_user_model().objects.create_user(username='staff', password='test-only', is_staff=True)
        self.client.force_login(user)
        return user

    def test_page_and_data_require_active_staff(self):
        for route in ('/admin/storage/', '/admin/storage/data/'):
            self.assertEqual(self.client.get(route).status_code, 302)
        user = get_user_model().objects.create_user(username='regular', password='test-only')
        self.client.force_login(user)
        self.assertEqual(self.client.get('/admin/storage/data/').status_code, 302)
        user.is_staff = True
        user.is_active = False
        user.save()
        self.assertEqual(self.client.get('/admin/storage/').status_code, 302)

    def test_staff_home_links_to_storage_and_refresh_is_read_only(self):
        self.staff()
        self.save()
        self.assertContains(self.client.get('/admin/'), '/admin/storage/')
        response = self.client.get('/admin/storage/')
        self.assertContains(response, '800 B')
        self.assertContains(response, '시스템 예약 공간')
        self.assertContains(response, '새로고침')
        self.assertIn('no-store', response.headers['Cache-Control'])
        data = self.client.get('/admin/storage/data/')
        self.assertIn('800 B', data.json()['html'])
        self.assertEqual(self.client.post('/admin/storage/data/').status_code, 405)

    def test_missing_snapshot_is_pending_not_zero_capacity(self):
        result = self.result()
        self.assertEqual(result['state'], 'pending')
        self.assertEqual(result['volumes'], [])

    def test_real_capacity_and_database_size_are_separate(self):
        self.save()
        result = self.result()
        self.assertEqual(result['state'], 'healthy')
        self.assertEqual(result['volumes'][0]['available'], '800 B')
        self.assertEqual(result['volumes'][0]['reserved'], '50 B')
        self.assertEqual(result['volumes'][0]['used_percent'], '15.0')
        self.assertEqual(result['sizes'][0]['size'], '117.7 MiB')

    def test_old_measurement_is_stale_even_if_just_received(self):
        self.payload['report']['measured_at'] -= 181
        self.save()
        self.assertEqual(self.result()['state'], 'stale')

    def test_transport_failure_keeps_last_value_and_timestamp(self):
        self.payload['error'] = 'connection failed'
        self.save()
        result = self.result()
        self.assertEqual(result['state'], 'error')
        self.assertEqual(result['volumes'][0]['available'], '800 B')
        self.assertEqual(result['measured_at'], self.now)

    def test_partial_measurement_failure_does_not_hide_disk_space(self):
        self.payload['report']['sizes'][0]['bytes'] = None
        self.payload['report']['errors'] = ['DB 데이터 크기를 조회하지 못했습니다.']
        self.save()
        result = self.result()
        self.assertEqual(result['state'], 'error')
        self.assertEqual(result['volumes'][0]['available'], '800 B')
        self.assertEqual(result['sizes'][0]['size'], '측정값 없음')

    def test_disk_and_inode_pressure_warn(self):
        for available, inodes, expected in ((50, 90, 'critical'), (100, 90, 'warning'), (800, 4, 'critical')):
            with self.subTest(available=available, inodes=inodes):
                volume = self.payload['report']['volumes'][0]
                volume.update(available_bytes=available, used_bytes=950-available, inode_available=inodes)
                self.save()
                self.assertEqual(self.result()['state'], expected)

    def test_invalid_snapshot_never_displays_capacity(self):
        for field, value in (('available_bytes', -1), ('available_bytes', 2000),
                             ('total_bytes', 0), ('used_bytes', True), ('inode_available', 200),
                             ('total_bytes', 2**64)):
            with self.subTest(field=field, value=value):
                self.payload = snapshot(self.now)
                self.payload['report']['volumes'][0][field] = value
                self.save()
                result = self.result()
                self.assertEqual(result['state'], 'error')
                self.assertEqual(result['volumes'], [])

    def test_mismatched_source_future_time_and_oversized_data_rejected(self):
        for field, value in (('source', 'crawler'), ('measured_at', self.now.timestamp()+121)):
            self.payload = snapshot(self.now)
            self.payload['report'][field] = value
            self.save()
            self.assertEqual(self.result()['state'], 'error')
        (Path(self.temp.name) / 'database.json').write_text('x' * (MAX_SNAPSHOT_BYTES + 1))
        self.assertEqual(self.result()['state'], 'error')

    def test_unreadable_snapshot_returns_a_visible_error(self):
        with patch('pathlib.Path.open', side_effect=PermissionError):
            self.assertEqual(self.result()['state'], 'error')

    def test_html_in_snapshot_is_escaped_in_page_and_refresh(self):
        self.staff()
        self.payload['report']['hostname'] = '<script>alert(1)</script>'
        self.save()
        self.assertContains(self.client.get('/admin/storage/'), '&lt;script&gt;')
        self.assertNotIn('<script>alert', self.client.get('/admin/storage/data/').json()['html'])
