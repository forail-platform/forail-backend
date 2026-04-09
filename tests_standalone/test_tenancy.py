"""Standalone tests for Multi-Tenancy v1 pure helpers.

Loads forge/main/tenancy/helpers.py directly via importlib — no Django.
"""

import os
import sys
import importlib.util
import unittest
from datetime import datetime, timedelta, timezone


def _load(mod_name, rel_path):
    path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', rel_path))
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


helpers = _load('tenancy_helpers', 'forge/main/tenancy/helpers.py')

check_quota_value = helpers.check_quota_value
is_window_expired = helpers.is_window_expired
reset_daily_window = helpers.reset_daily_window
format_quota_message = helpers.format_quota_message
normalize_host = helpers.normalize_host
is_valid_hex_color = helpers.is_valid_hex_color
validate_provisioning_payload = helpers.validate_provisioning_payload


class TestCheckQuotaValue(unittest.TestCase):
    def test_unlimited_none(self):
        self.assertTrue(check_quota_value(0, None))
        self.assertTrue(check_quota_value(9999, None))

    def test_unlimited_zero(self):
        self.assertTrue(check_quota_value(100, 0))

    def test_below_limit(self):
        self.assertTrue(check_quota_value(5, 10))

    def test_at_limit(self):
        self.assertFalse(check_quota_value(10, 10))

    def test_above_limit(self):
        self.assertFalse(check_quota_value(11, 10))


class TestIsWindowExpired(unittest.TestCase):
    def test_same_day(self):
        now = datetime(2026, 4, 9, 15, 30, tzinfo=timezone.utc)
        ws = datetime(2026, 4, 9, 0, 5, tzinfo=timezone.utc)
        self.assertFalse(is_window_expired(ws, now))

    def test_next_day(self):
        now = datetime(2026, 4, 10, 0, 0, 1, tzinfo=timezone.utc)
        ws = datetime(2026, 4, 9, 23, 59, 59, tzinfo=timezone.utc)
        self.assertTrue(is_window_expired(ws, now))

    def test_none_is_expired(self):
        self.assertTrue(is_window_expired(None, datetime.now(timezone.utc)))


class TestResetDailyWindow(unittest.TestCase):
    def test_top_of_day(self):
        now = datetime(2026, 4, 9, 15, 30, 5, tzinfo=timezone.utc)
        top, count = reset_daily_window(now)
        self.assertEqual(count, 0)
        self.assertEqual(top.date(), now.date())
        self.assertEqual((top.hour, top.minute, top.second), (0, 0, 0))

    def test_midnight_idempotent(self):
        now = datetime(2026, 4, 9, 0, 0, 0, tzinfo=timezone.utc)
        top, count = reset_daily_window(now)
        self.assertEqual(top, now)
        self.assertEqual(count, 0)


class TestFormatQuotaMessage(unittest.TestCase):
    def test_concurrent_jobs(self):
        self.assertIn('Concurrent jobs', format_quota_message('concurrent_jobs', 10, 10))
        self.assertIn('10/10', format_quota_message('concurrent_jobs', 10, 10))

    def test_daily_launches(self):
        self.assertIn('Daily launches', format_quota_message('daily_launches', 500, 500))

    def test_hosts(self):
        self.assertIn('Hosts', format_quota_message('hosts', 200, 200))

    def test_storage_mb(self):
        msg = format_quota_message('storage_mb', 5000, 5000)
        self.assertIn('Storage', msg)
        self.assertIn('5000/5000', msg)


class TestNormalizeHost(unittest.TestCase):
    def test_lowercase(self):
        self.assertEqual(normalize_host('ACME.Example.COM'), 'acme.example.com')

    def test_strip_port(self):
        self.assertEqual(normalize_host('acme.example.com:8080'), 'acme.example.com')

    def test_trailing_dot(self):
        self.assertEqual(normalize_host('acme.example.com.'), 'acme.example.com')

    def test_whitespace(self):
        self.assertEqual(normalize_host('  acme.example.com  '), 'acme.example.com')

    def test_none_and_empty(self):
        self.assertEqual(normalize_host(None), '')
        self.assertEqual(normalize_host(''), '')


class TestIsValidHexColor(unittest.TestCase):
    def test_valid(self):
        self.assertTrue(is_valid_hex_color('#5B47E0'))
        self.assertTrue(is_valid_hex_color('#000000'))
        self.assertTrue(is_valid_hex_color('#ffffff'))

    def test_missing_hash(self):
        self.assertFalse(is_valid_hex_color('5B47E0'))

    def test_wrong_length(self):
        self.assertFalse(is_valid_hex_color('#FFF'))
        self.assertFalse(is_valid_hex_color('#12345'))
        self.assertFalse(is_valid_hex_color('#1234567'))

    def test_non_hex(self):
        self.assertFalse(is_valid_hex_color('#ZZZZZZ'))

    def test_empty(self):
        self.assertFalse(is_valid_hex_color(''))
        self.assertFalse(is_valid_hex_color(None))


class TestValidateProvisioningPayload(unittest.TestCase):
    def _base(self):
        return {
            'name': 'Acme Corp',
            'admin_username': 'acme-admin',
            'admin_email': 'admin@acme.example',
            'admin_password': 'supersecret',
            'quota': {'max_concurrent_jobs': 10, 'max_daily_launches': 500},
            'branding': {'primary_color': '#5B47E0'},
        }

    def test_all_valid(self):
        self.assertEqual(validate_provisioning_payload(self._base()), [])

    def test_missing_name(self):
        p = self._base()
        p['name'] = ''
        errs = validate_provisioning_payload(p)
        self.assertTrue(any('name' in e for e in errs))

    def test_missing_admin_username(self):
        p = self._base()
        p['admin_username'] = 'ab'
        errs = validate_provisioning_payload(p)
        self.assertTrue(any('admin_username' in e for e in errs))

    def test_bad_email(self):
        p = self._base()
        p['admin_email'] = 'not-an-email'
        errs = validate_provisioning_payload(p)
        self.assertTrue(any('admin_email' in e for e in errs))

    def test_bad_password(self):
        p = self._base()
        p['admin_password'] = 'short'
        errs = validate_provisioning_payload(p)
        self.assertTrue(any('admin_password' in e for e in errs))

    def test_bad_color(self):
        p = self._base()
        p['branding']['primary_color'] = 'blue'
        errs = validate_provisioning_payload(p)
        self.assertTrue(any('primary_color' in e for e in errs))

    def test_negative_quota(self):
        p = self._base()
        p['quota']['max_hosts'] = -5
        errs = validate_provisioning_payload(p)
        self.assertTrue(any('max_hosts' in e for e in errs))

    def test_non_dict(self):
        self.assertTrue(validate_provisioning_payload('nope'))


if __name__ == '__main__':
    unittest.main()
