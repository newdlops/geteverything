import base64
from contextlib import redirect_stdout
import csv
import gzip
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('ppomppu_vpn_guard', Path(__file__).with_name('guard.py'))
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def relay():
    return {'ip': '1.1.1.1', 'port': 443, 'proto': 'tcp', 'score': 1, 'blocks': {
        'ca': '-----BEGIN CERTIFICATE-----\nYWJj\n-----END CERTIFICATE-----',
        'cert': '-----BEGIN CERTIFICATE-----\nYWJj\n-----END CERTIFICATE-----',
        'key': '-----BEGIN PRIVATE KEY-----\nYWJj\n-----END PRIVATE KEY-----'}}


def catalog_csv(candidates):
    output = io.StringIO()
    output.write('*vpn_servers\n')
    writer = csv.writer(output)
    writer.writerow(['#HostName', 'IP', 'CountryShort', 'Score', 'OpenVPN_ConfigData_Base64'])
    for candidate in candidates:
        writer.writerow(['test', candidate['ip'], candidate.get('country', 'KR'), candidate['score'],
                         base64.b64encode(guard.profile_for(candidate).encode()).decode()])
    return output.getvalue()


class GuardTests(unittest.TestCase):
    def test_only_public_ipv4_endpoints_are_accepted(self):
        for address in ('127.0.0.1', '169.254.169.254', '10.0.0.51', '::1', '2001:4860:4860::8888'):
            candidate = relay()
            candidate['ip'] = address
            with self.subTest(address=address), self.assertRaises(ValueError):
                guard.profile_for(candidate)

    def test_pem_cannot_inject_openvpn_commands(self):
        for name in ('ca', 'cert', 'key'):
            candidate = relay()
            candidate['blocks'][name] += '\n</' + name + '>\nscript-security 2\nup /bin/sh'
            with self.subTest(block=name), self.assertRaises(ValueError):
                guard.profile_for(candidate)

    def test_profile_is_generated_and_keeps_certificate_checks(self):
        candidate = relay()
        candidate['directives'] = ['up /bin/sh', 'script-security 2']
        profile = guard.profile_for(candidate)
        self.assertNotIn('up /bin/sh', profile)
        self.assertIn('script-security 1\n', profile)
        self.assertIn('verify-x509-name opengw.net name\n', profile)
        self.assertIn('remote-cert-tls server\n', profile)
        self.assertIn('connect-retry-max 1\n', profile)

    def test_unowned_container_is_never_removed(self):
        result = type('Result', (), {'returncode': 0, 'stdout': '[{"Config":{"Labels":{}}}]'})()
        with patch.object(guard, 'run', return_value=result) as command:
            with self.assertRaises(RuntimeError):
                guard.remove_owned()
        self.assertEqual(command.call_count, 1)

    def test_truncated_server_list_is_rejected(self):
        with self.assertRaises(ValueError):
            guard.parse_relays('*vpn_servers')

    def test_failed_relays_are_skipped_across_recovery_cycles(self):
        candidates = [dict(relay(), ip='1.1.' + str(i) + '.1') for i in range(1, 7)]
        state = {'failed_until': {'1.1.1.1': 200, '1.1.2.1': 200, '1.1.3.1': 200}}
        self.assertEqual([r['ip'] for r in guard.available_candidates(candidates, state, 100)],
                         ['1.1.4.1', '1.1.5.1', '1.1.6.1'])
        self.assertEqual(guard.available_candidates(candidates, state, 201), candidates[:3])

    def test_host_dns_rejects_private_targets(self):
        result = type('Result', (), {'stdout': '169.254.169.254 STREAM target\n'})()
        with patch.object(guard, 'run', return_value=result), self.assertRaises(ValueError):
            guard.host_addresses()

    def test_recovery_includes_a_different_region(self):
        candidates = [dict(relay(), ip='1.1.' + str(i) + '.1', country='KR') for i in range(1, 5)]
        candidates.append(dict(relay(), ip='8.8.8.8', country='JP'))
        self.assertEqual([r['ip'] for r in guard.available_candidates(candidates, {}, 100)],
                         ['1.1.1.1', '8.8.8.8', '1.1.2.1'])

    def test_403_prefix_is_avoided_until_cooldown_expires(self):
        candidates = [dict(relay(), ip='219.100.37.24'), dict(relay(), ip='219.100.37.86'), relay()]
        state = {'failed_prefix_until': {'219.100.37.0/24': 200}}
        self.assertEqual(guard.available_candidates(candidates, state, 100), candidates[-1:])
        self.assertEqual(guard.available_candidates(candidates, state, 201), [relay(), candidates[0]])

    def test_expired_cooldown_does_not_starve_untried_low_score_relays(self):
        tried = dict(relay(), score=99999)
        fresh = dict(relay(), ip='8.8.8.8', country='TH', score=1)
        state = {'failed_until': {tried['ip']: 10}, 'attempt_history': {tried['ip']: {'at': 5, 'count': 1}}}
        self.assertEqual(guard.available_candidates([tried, fresh], state, 100), [fresh])

    def test_after_full_pass_the_oldest_attempt_is_selected_first(self):
        old = dict(relay(), ip='8.8.8.8', country='TH')
        recent = dict(relay(), score=99999)
        state = {'attempt_history': {old['ip']: {'at': 10}, recent['ip']: {'at': 99}}}
        self.assertEqual(guard.available_candidates([recent, old], state, 100)[0], old)

    def test_official_catalog_accepts_new_countries_and_deduplicates_ips(self):
        candidate = dict(relay(), country='TH')
        result = guard.parse_relays(catalog_csv([candidate, candidate]))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['country'], 'TH')

    def test_catalog_refresh_tracks_new_relays_without_retrying_within_five_minutes(self):
        first = dict(relay(), country='KR')
        second = dict(relay(), ip='8.8.8.8', country='TH')
        with tempfile.TemporaryDirectory() as directory, patch.object(guard, 'ROOT', Path(directory)), \
                patch.object(guard.time, 'time', return_value=1000) as clock, \
                patch.object(guard, 'run') as command, redirect_stdout(io.StringIO()):
            command.return_value.stdout = catalog_csv([first])
            self.assertEqual(len(guard.load_candidates()), 1)
            clock.return_value = 1100
            self.assertEqual(len(guard.load_candidates()), 1)
            self.assertEqual(command.call_count, 1)
            clock.return_value = 1301
            command.return_value.stdout = catalog_csv([first, second])
            self.assertEqual(len(guard.load_candidates()), 2)
            metadata = json.loads((guard.ROOT / 'catalog.json').read_text())
            self.assertEqual(metadata['added'], 1)
            self.assertEqual(metadata['countries'], {'KR': 1, 'TH': 1})
            self.assertEqual(metadata['fetched_at'], 1301)

    def test_failed_refresh_does_not_mark_stale_cache_as_new(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(guard, 'ROOT', Path(directory)), \
                patch.object(guard.time, 'time', return_value=1000), patch.object(guard, 'run') as command:
            guard.write_private(guard.ROOT / 'candidates.json', json.dumps([relay()]))
            guard.write_private(guard.ROOT / 'catalog.json', json.dumps({'version': 2, 'fetched_at': 100}))
            command.return_value.stdout = 'invalid catalog'
            self.assertEqual(guard.load_candidates(), [relay()])
            self.assertEqual(json.loads((guard.ROOT / 'catalog.json').read_text())['fetched_at'], 100)

    def test_probe_accepts_gzipped_real_list_and_requests_supported_compression(self):
        response = io.BytesIO(gzip.compress(b'<table><tr class="bbs_new1"><td>123</td></tr></table>'))
        response.status = 200
        response.headers = {'Content-Encoding': 'gzip'}
        opener = Mock()
        opener.open.return_value = response
        with patch.object(guard.urllib.request, 'build_opener', return_value=opener):
            self.assertTrue(guard.healthy())
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_header('Accept-encoding'), 'gzip, deflate')
        self.assertEqual(request.get_header('Accept'), '*/*')

    def test_gzipped_error_html_is_not_a_success(self):
        response = io.BytesIO(gzip.compress(b'<title>403 Forbidden</title>'))
        response.status = 200
        response.headers = {'Content-Encoding': 'gzip'}
        opener = Mock()
        opener.open.return_value = response
        with patch.object(guard.urllib.request, 'build_opener', return_value=opener):
            self.assertFalse(guard.healthy())


if __name__ == '__main__':
    unittest.main()
