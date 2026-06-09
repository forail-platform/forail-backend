"""Standalone tests for Multi-Tenancy v1 pure helpers.

Loads forail/main/tenancy/helpers.py directly via importlib — no Django.
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


helpers = _load('tenancy_helpers', 'forail/main/tenancy/helpers.py')

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


# ---------------------------------------------------------------------------
# Multi-Tenancy v2: RLS helper tests
# ---------------------------------------------------------------------------

build_rls_policy_sql = helpers.build_rls_policy_sql
build_rls_policy_sql_indirect = helpers.build_rls_policy_sql_indirect
RLS_TABLES_DIRECT = helpers.RLS_TABLES_DIRECT
RLS_TABLES_INDIRECT = helpers.RLS_TABLES_INDIRECT


class TestBuildRlsPolicySql(unittest.TestCase):
    """Test SQL generation for direct RLS policies."""

    def test_returns_tuple(self):
        create, drop = build_rls_policy_sql('main_inventory', 'organization_id')
        self.assertIsInstance(create, str)
        self.assertIsInstance(drop, str)

    def test_create_contains_policy_name(self):
        create, _ = build_rls_policy_sql('main_inventory', 'organization_id')
        self.assertIn('tenant_isolation_main_inventory', create)

    def test_create_contains_org_column(self):
        create, _ = build_rls_policy_sql('main_inventory', 'organization_id')
        self.assertIn('organization_id = current_setting', create)

    def test_create_contains_bypass_clauses(self):
        create, _ = build_rls_policy_sql('main_inventory', 'organization_id')
        # Bypass when session var is NULL
        self.assertIn("IS NULL", create)
        # Bypass when session var is empty string
        self.assertIn("= ''", create)
        # Bypass when org column is NULL (shared resources)
        self.assertIn('organization_id IS NULL', create)

    def test_create_is_permissive(self):
        create, _ = build_rls_policy_sql('main_inventory', 'organization_id')
        self.assertIn('AS PERMISSIVE', create)

    def test_drop_contains_policy_name(self):
        _, drop = build_rls_policy_sql('main_inventory', 'organization_id')
        self.assertIn('DROP POLICY IF EXISTS tenant_isolation_main_inventory', drop)

    def test_different_tables_produce_different_policies(self):
        c1, _ = build_rls_policy_sql('main_inventory', 'organization_id')
        c2, _ = build_rls_policy_sql('main_credential', 'organization_id')
        self.assertIn('main_inventory', c1)
        self.assertIn('main_credential', c2)
        self.assertNotEqual(c1, c2)


class TestBuildRlsPolicySqlIndirect(unittest.TestCase):
    """Test SQL generation for indirect (subquery-based) RLS policies."""

    def test_returns_tuple(self):
        create, drop = build_rls_policy_sql_indirect(
            'main_host', 'inventory_id', 'main_inventory', 'organization_id'
        )
        self.assertIsInstance(create, str)
        self.assertIsInstance(drop, str)

    def test_create_contains_subquery(self):
        create, _ = build_rls_policy_sql_indirect(
            'main_host', 'inventory_id', 'main_inventory', 'organization_id'
        )
        self.assertIn('SELECT id FROM main_inventory', create)
        self.assertIn('inventory_id IN', create)

    def test_create_contains_bypass(self):
        create, _ = build_rls_policy_sql_indirect(
            'main_host', 'inventory_id', 'main_inventory', 'organization_id'
        )
        self.assertIn("IS NULL", create)
        self.assertIn("= ''", create)

    def test_drop_contains_policy_name(self):
        _, drop = build_rls_policy_sql_indirect(
            'main_host', 'inventory_id', 'main_inventory', 'organization_id'
        )
        self.assertIn('DROP POLICY IF EXISTS tenant_isolation_main_host', drop)


class TestRlsTablesConstant(unittest.TestCase):
    """Validate the RLS_TABLES_DIRECT and RLS_TABLES_INDIRECT constants."""

    def test_direct_tables_not_empty(self):
        self.assertGreater(len(RLS_TABLES_DIRECT), 10)

    def test_indirect_tables_not_empty(self):
        self.assertGreater(len(RLS_TABLES_INDIRECT), 0)

    def test_direct_entries_are_tuples(self):
        for entry in RLS_TABLES_DIRECT:
            self.assertEqual(len(entry), 2, f'Bad entry: {entry}')
            table, col = entry
            self.assertTrue(table.startswith('main_'), f'Unexpected table: {table}')
            self.assertEqual(col, 'organization_id', f'Unexpected column: {col} for {table}')

    def test_indirect_entries_are_tuples(self):
        for entry in RLS_TABLES_INDIRECT:
            self.assertEqual(len(entry), 4, f'Bad entry: {entry}')

    def test_no_duplicate_tables(self):
        direct_tables = [t for t, _ in RLS_TABLES_DIRECT]
        indirect_tables = [t for t, _, _, _ in RLS_TABLES_INDIRECT]
        all_tables = direct_tables + indirect_tables
        self.assertEqual(len(all_tables), len(set(all_tables)), 'Duplicate table in RLS lists')

    def test_core_tables_present(self):
        direct_tables = {t for t, _ in RLS_TABLES_DIRECT}
        for expected in ['main_inventory', 'main_credential', 'main_team',
                         'main_unifiedjobtemplate', 'main_unifiedjob']:
            self.assertIn(expected, direct_tables, f'{expected} missing from RLS_TABLES_DIRECT')

    def test_host_is_indirect(self):
        indirect_tables = {t for t, _, _, _ in RLS_TABLES_INDIRECT}
        self.assertIn('main_host', indirect_tables)


# ---------------------------------------------------------------------------
# Multi-Tenancy v2: Strict Isolation helper tests
# ---------------------------------------------------------------------------

should_exempt_isolation = helpers.should_exempt_isolation
make_isolation_decision = helpers.make_isolation_decision
ISOLATION_EXEMPT_PATH_PREFIXES = helpers.ISOLATION_EXEMPT_PATH_PREFIXES


class TestShouldExemptIsolation(unittest.TestCase):
    """Test path exemption checks for strict isolation."""

    def test_none_path(self):
        self.assertTrue(should_exempt_isolation(None))

    def test_empty_path(self):
        self.assertTrue(should_exempt_isolation(''))

    def test_branding_exempt(self):
        self.assertTrue(should_exempt_isolation('/api/v2/branding/'))

    def test_config_exempt(self):
        self.assertTrue(should_exempt_isolation('/api/v2/config/'))

    def test_tenants_exempt(self):
        self.assertTrue(should_exempt_isolation('/api/v2/tenants/'))

    def test_login_exempt(self):
        self.assertTrue(should_exempt_isolation('/api/login/'))

    def test_sso_exempt(self):
        self.assertTrue(should_exempt_isolation('/sso/login/'))

    def test_isolation_events_exempt(self):
        self.assertTrue(should_exempt_isolation('/api/v2/tenant_isolation_events/'))

    def test_inventories_not_exempt(self):
        self.assertFalse(should_exempt_isolation('/api/v2/inventories/'))

    def test_hosts_not_exempt(self):
        self.assertFalse(should_exempt_isolation('/api/v2/hosts/5/'))

    def test_job_templates_not_exempt(self):
        self.assertFalse(should_exempt_isolation('/api/v2/job_templates/'))


class TestMakeIsolationDecision(unittest.TestCase):
    """Test isolation decision logic."""

    def test_same_tenant_no_action(self):
        block, audit = make_isolation_decision(True, True, is_cross_tenant=False)
        self.assertFalse(block)
        self.assertFalse(audit)

    def test_cross_tenant_both_strict(self):
        block, audit = make_isolation_decision(True, True, is_cross_tenant=True)
        self.assertTrue(block)
        self.assertTrue(audit)

    def test_cross_tenant_org_strict_global_off(self):
        block, audit = make_isolation_decision(True, False, is_cross_tenant=True)
        self.assertFalse(block)
        self.assertTrue(audit)

    def test_cross_tenant_org_not_strict(self):
        block, audit = make_isolation_decision(False, True, is_cross_tenant=True)
        self.assertFalse(block)
        self.assertTrue(audit)

    def test_cross_tenant_neither_strict(self):
        block, audit = make_isolation_decision(False, False, is_cross_tenant=True)
        self.assertFalse(block)
        self.assertTrue(audit)


class TestIsolationExemptPrefixes(unittest.TestCase):
    """Validate the ISOLATION_EXEMPT_PATH_PREFIXES constant."""

    def test_not_empty(self):
        self.assertGreater(len(ISOLATION_EXEMPT_PATH_PREFIXES), 5)

    def test_all_start_with_slash(self):
        for prefix in ISOLATION_EXEMPT_PATH_PREFIXES:
            self.assertTrue(prefix.startswith('/'), f'{prefix} should start with /')


# ---------------------------------------------------------------------------
# Multi-Tenancy v2: Rate Limiting helper tests
# ---------------------------------------------------------------------------

compute_token_bucket_params = helpers.compute_token_bucket_params
TOKEN_BUCKET_LUA = helpers.TOKEN_BUCKET_LUA


class TestComputeTokenBucketParams(unittest.TestCase):
    """Test token bucket parameter computation."""

    def test_none_returns_zeros(self):
        self.assertEqual(compute_token_bucket_params(None), (0, 0))

    def test_zero_returns_zeros(self):
        self.assertEqual(compute_token_bucket_params(0), (0, 0))

    def test_negative_returns_zeros(self):
        self.assertEqual(compute_token_bucket_params(-5), (0, 0))

    def test_positive_rate(self):
        max_tokens, refill_rate = compute_token_bucket_params(100)
        self.assertEqual(refill_rate, 100)
        self.assertEqual(max_tokens, 200)  # burst_multiplier=2

    def test_custom_burst_multiplier(self):
        max_tokens, refill_rate = compute_token_bucket_params(50, burst_multiplier=3)
        self.assertEqual(refill_rate, 50)
        self.assertEqual(max_tokens, 150)

    def test_one_req_per_sec(self):
        max_tokens, refill_rate = compute_token_bucket_params(1)
        self.assertEqual(refill_rate, 1)
        self.assertEqual(max_tokens, 2)


class TestTokenBucketLua(unittest.TestCase):
    """Validate structure of the Lua script."""

    def test_is_non_empty_string(self):
        self.assertIsInstance(TOKEN_BUCKET_LUA, str)
        self.assertGreater(len(TOKEN_BUCKET_LUA), 100)

    def test_uses_keys_and_argv(self):
        self.assertIn('KEYS[1]', TOKEN_BUCKET_LUA)
        self.assertIn('ARGV[1]', TOKEN_BUCKET_LUA)
        self.assertIn('ARGV[2]', TOKEN_BUCKET_LUA)
        self.assertIn('ARGV[3]', TOKEN_BUCKET_LUA)

    def test_returns_allowed_flag(self):
        self.assertIn('allowed', TOKEN_BUCKET_LUA)

    def test_uses_hmget_hmset(self):
        self.assertIn('HMGET', TOKEN_BUCKET_LUA)
        self.assertIn('HMSET', TOKEN_BUCKET_LUA)

    def test_sets_expire(self):
        self.assertIn('EXPIRE', TOKEN_BUCKET_LUA)


# ---------------------------------------------------------------------------
# Multi-Tenancy v2: Celery Queue helper tests
# ---------------------------------------------------------------------------

tenant_queue_name_fn = helpers.tenant_queue_name
TENANT_QUEUE_PREFIX = helpers.TENANT_QUEUE_PREFIX


class TestTenantQueueName(unittest.TestCase):
    """Test tenant queue name generation."""

    def test_valid_org_id(self):
        self.assertEqual(tenant_queue_name_fn(42), 'tenant-42')

    def test_string_org_id(self):
        self.assertEqual(tenant_queue_name_fn('99'), 'tenant-99')

    def test_none_returns_empty(self):
        self.assertEqual(tenant_queue_name_fn(None), '')

    def test_zero_returns_empty(self):
        self.assertEqual(tenant_queue_name_fn(0), '')

    def test_prefix_constant(self):
        self.assertEqual(TENANT_QUEUE_PREFIX, 'tenant-')

    def test_name_starts_with_prefix(self):
        name = tenant_queue_name_fn(1)
        self.assertTrue(name.startswith(TENANT_QUEUE_PREFIX))


if __name__ == '__main__':
    unittest.main()
