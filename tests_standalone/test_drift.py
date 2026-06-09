"""
Standalone tests for Drift Detection logic.

Covers: compute_drift, fact hashing, category classification,
severity assignment, alert threshold evaluation.
"""

import hashlib
import json
import unittest
from datetime import datetime, timedelta, timezone


# ---------------------------------------------------------------------------
# Import task-level pure functions directly (avoid Django imports)
# ---------------------------------------------------------------------------
import sys
import os
import importlib.util

# Load drift module directly to avoid Django/Celery dependency chain
_drift_path = os.path.join(os.path.dirname(__file__), '..', 'forail', 'main', 'tasks', 'drift.py')
_drift_path = os.path.abspath(_drift_path)

# We need to mock celery.shared_task before importing
import types
_mock_celery = types.ModuleType('celery')
_mock_celery.shared_task = lambda *a, **kw: (lambda f: f)
sys.modules['celery'] = _mock_celery

# Also need to stub django modules used at module level
for mod_name in ['django', 'django.utils', 'django.utils.timezone', 'django.db', 'django.db.models']:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = types.ModuleType(mod_name)

# Provide django.utils.timezone.now
_tz_mod = sys.modules['django.utils.timezone']
_tz_mod.now = lambda: datetime.now(timezone.utc)

# Provide django.db.models.F
_models_mod = sys.modules['django.db.models']
_models_mod.F = lambda x: x
_models_mod.Q = lambda **kw: kw

spec = importlib.util.spec_from_file_location('drift', _drift_path)
drift_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(drift_module)

_compute_facts_hash = drift_module._compute_facts_hash
_classify_fact = drift_module._classify_fact
_diff_type = drift_module._diff_type
_summarize_change = drift_module._summarize_change
compute_drift = drift_module.compute_drift
SEVERITY_ORDER = drift_module.SEVERITY_ORDER
CATEGORY_MAP = drift_module.CATEGORY_MAP


class TestFactsHash(unittest.TestCase):
    """Test that fact hashing is deterministic and consistent."""

    def test_same_dict_same_hash(self):
        facts = {'ansible_hostname': 'web01', 'ansible_os_family': 'Debian'}
        h1 = _compute_facts_hash(facts)
        h2 = _compute_facts_hash(facts)
        self.assertEqual(h1, h2)

    def test_key_order_independent(self):
        facts_a = {'b': 2, 'a': 1}
        facts_b = {'a': 1, 'b': 2}
        self.assertEqual(_compute_facts_hash(facts_a), _compute_facts_hash(facts_b))

    def test_different_dicts_different_hash(self):
        h1 = _compute_facts_hash({'key': 'value1'})
        h2 = _compute_facts_hash({'key': 'value2'})
        self.assertNotEqual(h1, h2)

    def test_empty_dict(self):
        h = _compute_facts_hash({})
        # Should be the sha256 of "{}"
        expected = hashlib.sha256(b'{}').hexdigest()
        self.assertEqual(h, expected)

    def test_hash_length(self):
        h = _compute_facts_hash({'x': 1})
        self.assertEqual(len(h), 64)  # SHA-256 hex digest


class TestCategoryClassification(unittest.TestCase):
    """Test fact key -> category mapping."""

    def test_known_package_keys(self):
        cat, sev = _classify_fact('ansible_packages')
        self.assertEqual(cat, 'packages')
        self.assertEqual(sev, 'medium')

    def test_known_service_keys(self):
        cat, sev = _classify_fact('ansible_services')
        self.assertEqual(cat, 'services')
        self.assertEqual(sev, 'medium')

    def test_known_user_keys(self):
        cat, sev = _classify_fact('ansible_user_id')
        self.assertEqual(cat, 'users_groups')
        self.assertEqual(sev, 'high')

    def test_known_network_keys(self):
        cat, sev = _classify_fact('ansible_all_ipv4_addresses')
        self.assertEqual(cat, 'network')
        self.assertEqual(sev, 'high')

    def test_known_mount_keys(self):
        cat, sev = _classify_fact('ansible_mounts')
        self.assertEqual(cat, 'mounts')
        self.assertEqual(sev, 'medium')

    def test_known_kernel_keys(self):
        cat, sev = _classify_fact('ansible_kernel')
        self.assertEqual(cat, 'kernel')
        self.assertEqual(sev, 'critical')

    def test_unknown_key_defaults_to_other(self):
        cat, sev = _classify_fact('ansible_custom_unknown_fact')
        self.assertEqual(cat, 'other')
        self.assertEqual(sev, 'low')

    def test_pattern_fallback_package(self):
        cat, sev = _classify_fact('custom_pip_packages')
        self.assertEqual(cat, 'packages')

    def test_pattern_fallback_service(self):
        cat, sev = _classify_fact('custom_systemd_units')
        self.assertEqual(cat, 'services')

    def test_pattern_fallback_user(self):
        cat, sev = _classify_fact('local_user_accounts')
        self.assertEqual(cat, 'users_groups')

    def test_pattern_fallback_network(self):
        cat, sev = _classify_fact('open_tcp_ports')
        self.assertEqual(cat, 'network')

    def test_pattern_fallback_kernel(self):
        cat, sev = _classify_fact('custom_sysctl_settings')
        self.assertEqual(cat, 'kernel')


class TestDiffType(unittest.TestCase):
    """Test diff type classification."""

    def test_added(self):
        self.assertEqual(_diff_type(None, 'new'), 'added')

    def test_removed(self):
        self.assertEqual(_diff_type('old', None), 'removed')

    def test_changed(self):
        self.assertEqual(_diff_type('old', 'new'), 'changed')


class TestSummarizeChange(unittest.TestCase):
    """Test human-readable summary generation."""

    def test_added(self):
        s = _summarize_change('ansible_new', None, 'value', 'added')
        self.assertIn('added', s)

    def test_removed(self):
        s = _summarize_change('ansible_old', 'value', None, 'removed')
        self.assertIn('removed', s)

    def test_list_change(self):
        s = _summarize_change('ansible_packages', ['a', 'b'], ['a', 'b', 'c'], 'changed')
        self.assertIn('+1', s)

    def test_dict_change(self):
        old = {'key1': 'v1', 'key2': 'v2'}
        new = {'key1': 'v1_modified', 'key3': 'v3'}
        s = _summarize_change('ansible_services', old, new, 'changed')
        self.assertIn('keys', s)

    def test_scalar_change(self):
        s = _summarize_change('ansible_hostname', 'web01', 'web02', 'changed')
        self.assertIn('web01', s)
        self.assertIn('web02', s)


class TestComputeDrift(unittest.TestCase):
    """Test the main drift computation function."""

    def test_identical_facts_no_drift(self):
        facts = {'ansible_hostname': 'web01', 'ansible_os_family': 'Debian'}
        drifts = compute_drift(facts, facts.copy())
        self.assertEqual(len(drifts), 0)

    def test_added_fact(self):
        old = {'ansible_hostname': 'web01'}
        new = {'ansible_hostname': 'web01', 'ansible_packages': {'nginx': '1.0'}}
        drifts = compute_drift(old, new)
        self.assertEqual(len(drifts), 1)
        self.assertEqual(drifts[0]['fact_path'], 'ansible_packages')
        self.assertEqual(drifts[0]['detail']['diff_type'], 'added')
        self.assertEqual(drifts[0]['category'], 'packages')

    def test_removed_fact(self):
        old = {'ansible_hostname': 'web01', 'ansible_services': {'nginx': 'running'}}
        new = {'ansible_hostname': 'web01'}
        drifts = compute_drift(old, new)
        self.assertEqual(len(drifts), 1)
        self.assertEqual(drifts[0]['detail']['diff_type'], 'removed')

    def test_changed_fact(self):
        old = {'ansible_hostname': 'web01'}
        new = {'ansible_hostname': 'web02'}
        drifts = compute_drift(old, new)
        self.assertEqual(len(drifts), 1)
        self.assertEqual(drifts[0]['detail']['diff_type'], 'changed')

    def test_volatile_keys_skipped(self):
        old = {'ansible_date_time': {'epoch': '1000'}, 'ansible_uptime_seconds': 3600}
        new = {'ansible_date_time': {'epoch': '2000'}, 'ansible_uptime_seconds': 7200}
        drifts = compute_drift(old, new)
        self.assertEqual(len(drifts), 0)

    def test_multiple_changes(self):
        old = {
            'ansible_hostname': 'web01',
            'ansible_packages': {'nginx': '1.18'},
            'ansible_kernel': '5.4.0',
        }
        new = {
            'ansible_hostname': 'web02',
            'ansible_packages': {'nginx': '1.24'},
            'ansible_kernel': '6.1.0',
        }
        drifts = compute_drift(old, new)
        self.assertEqual(len(drifts), 3)

        # Check they're sorted by key
        paths = [d['fact_path'] for d in drifts]
        self.assertEqual(paths, sorted(paths))

    def test_kernel_change_is_critical(self):
        old = {'ansible_kernel': '5.4.0'}
        new = {'ansible_kernel': '6.1.0'}
        drifts = compute_drift(old, new)
        self.assertEqual(drifts[0]['severity'], 'critical')

    def test_user_change_is_high(self):
        old = {'ansible_user_id': 'deploy'}
        new = {'ansible_user_id': 'root'}
        drifts = compute_drift(old, new)
        self.assertEqual(drifts[0]['severity'], 'high')
        self.assertEqual(drifts[0]['category'], 'users_groups')

    def test_empty_to_populated(self):
        old = {}
        new = {'ansible_hostname': 'web01', 'ansible_kernel': '5.4.0'}
        drifts = compute_drift(old, new)
        self.assertEqual(len(drifts), 2)
        for d in drifts:
            self.assertEqual(d['detail']['diff_type'], 'added')

    def test_populated_to_empty(self):
        old = {'ansible_hostname': 'web01'}
        new = {}
        drifts = compute_drift(old, new)
        self.assertEqual(len(drifts), 1)
        self.assertEqual(drifts[0]['detail']['diff_type'], 'removed')

    def test_drift_output_structure(self):
        old = {'ansible_hostname': 'web01'}
        new = {'ansible_hostname': 'web02'}
        drifts = compute_drift(old, new)
        d = drifts[0]
        self.assertIn('fact_path', d)
        self.assertIn('category', d)
        self.assertIn('severity', d)
        self.assertIn('summary', d)
        self.assertIn('detail', d)
        self.assertIn('before', d['detail'])
        self.assertIn('after', d['detail'])
        self.assertIn('diff_type', d['detail'])


class TestSeverityOrder(unittest.TestCase):
    """Test severity ordering for threshold comparisons."""

    def test_order_values(self):
        self.assertLess(SEVERITY_ORDER['low'], SEVERITY_ORDER['medium'])
        self.assertLess(SEVERITY_ORDER['medium'], SEVERITY_ORDER['high'])
        self.assertLess(SEVERITY_ORDER['high'], SEVERITY_ORDER['critical'])

    def test_all_severities_present(self):
        expected = {'low', 'medium', 'high', 'critical'}
        self.assertEqual(set(SEVERITY_ORDER.keys()), expected)


class TestCategoryMap(unittest.TestCase):
    """Test that all known fact keys have valid categories."""

    VALID_CATEGORIES = {'packages', 'services', 'users_groups', 'network', 'mounts', 'kernel', 'other'}
    VALID_SEVERITIES = {'low', 'medium', 'high', 'critical'}

    def test_all_mapped_categories_valid(self):
        for key, (cat, sev) in CATEGORY_MAP.items():
            self.assertIn(cat, self.VALID_CATEGORIES, f'Invalid category for {key}')
            self.assertIn(sev, self.VALID_SEVERITIES, f'Invalid severity for {key}')


if __name__ == '__main__':
    unittest.main()
