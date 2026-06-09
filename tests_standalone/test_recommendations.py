"""Standalone unit tests for the pure recommendations engine.

These tests do NOT import Django. They load ``types.py`` and ``rules.py``
directly, then load the pure ``evaluate`` helper from ``engine.py`` by
pre-stubbing ``forail.main.recommendations.types`` and
``forail.main.recommendations.rules`` in ``sys.modules``.
"""

import os
import sys
import types as _pytypes
import unittest
import importlib.util
from datetime import datetime, timedelta, timezone


def _load_as(mod_name, rel_path):
    path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', rel_path))
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


# Create package shells so relative imports in rules.py / engine.py resolve.
for pkg in ('forail', 'forail.main', 'forail.main.recommendations'):
    if pkg not in sys.modules:
        m = _pytypes.ModuleType(pkg)
        m.__path__ = []  # mark as package
        sys.modules[pkg] = m

rec_types = _load_as('forail.main.recommendations.types', 'forail/main/recommendations/types.py')
rec_rules = _load_as('forail.main.recommendations.rules', 'forail/main/recommendations/rules.py')
rec_engine = _load_as('forail.main.recommendations.engine', 'forail/main/recommendations/engine.py')

Recommendation = rec_types.Recommendation
RuleContext = rec_types.RuleContext
SEVERITY_INFO = rec_types.SEVERITY_INFO
SEVERITY_WARN = rec_types.SEVERITY_WARN
SEVERITY_CRITICAL = rec_types.SEVERITY_CRITICAL
evaluate = rec_engine.evaluate


# -- Individual rule tests ---------------------------------------------------


class TestRuleNoScanners(unittest.TestCase):
    def test_fires(self):
        ctx = RuleContext(job_templates_total=3, scanners_enabled_count=0)
        self.assertIsNotNone(rec_rules.rule_no_scanners(ctx))

    def test_does_not_fire(self):
        ctx = RuleContext(job_templates_total=3, scanners_enabled_count=1)
        self.assertIsNone(rec_rules.rule_no_scanners(ctx))


class TestRuleAllPoliciesWarn(unittest.TestCase):
    def test_fires(self):
        ctx = RuleContext(policies_total=5, policies_enforce_count=0)
        self.assertIsNotNone(rec_rules.rule_all_policies_warn(ctx))

    def test_does_not_fire(self):
        ctx = RuleContext(policies_total=5, policies_enforce_count=2)
        self.assertIsNone(rec_rules.rule_all_policies_warn(ctx))


class TestRuleMultiOrgNoTenancy(unittest.TestCase):
    def test_fires(self):
        ctx = RuleContext(organizations_total=3, tenancy_enabled=False)
        self.assertIsNotNone(rec_rules.rule_multi_org_no_tenancy(ctx))

    def test_does_not_fire(self):
        ctx = RuleContext(organizations_total=3, tenancy_enabled=True)
        self.assertIsNone(rec_rules.rule_multi_org_no_tenancy(ctx))


class TestRuleNoObservability(unittest.TestCase):
    def test_fires(self):
        ctx = RuleContext(otel_enabled=False)
        self.assertIsNotNone(rec_rules.rule_no_observability(ctx))

    def test_does_not_fire(self):
        ctx = RuleContext(otel_enabled=True)
        self.assertIsNone(rec_rules.rule_no_observability(ctx))


class TestRuleStaleProject(unittest.TestCase):
    def test_fires_none_sync(self):
        ctx = RuleContext(projects=[('proj1', None)])
        rec = rec_rules.rule_stale_project(ctx)
        self.assertIsNotNone(rec)
        self.assertIn('proj1', rec.why)

    def test_does_not_fire_recent(self):
        recent = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        ctx = RuleContext(projects=[('proj1', recent)])
        self.assertIsNone(rec_rules.rule_stale_project(ctx))


class TestRuleNoSchedules(unittest.TestCase):
    def test_fires(self):
        ctx = RuleContext(job_templates_total=2, schedules_total=0)
        self.assertIsNotNone(rec_rules.rule_no_schedules(ctx))

    def test_does_not_fire(self):
        ctx = RuleContext(job_templates_total=2, schedules_total=1)
        self.assertIsNone(rec_rules.rule_no_schedules(ctx))


class TestRuleNoDrift(unittest.TestCase):
    def test_fires(self):
        ctx = RuleContext(job_templates_total=2, drift_detections_total=0)
        self.assertIsNotNone(rec_rules.rule_no_drift(ctx))

    def test_does_not_fire(self):
        ctx = RuleContext(job_templates_total=2, drift_detections_total=5)
        self.assertIsNone(rec_rules.rule_no_drift(ctx))


class TestRuleFewSurveys(unittest.TestCase):
    def test_fires(self):
        ctx = RuleContext(job_templates_total=10, surveys_total=2)
        self.assertIsNotNone(rec_rules.rule_few_surveys(ctx))

    def test_does_not_fire_enough(self):
        ctx = RuleContext(job_templates_total=10, surveys_total=6)
        self.assertIsNone(rec_rules.rule_few_surveys(ctx))

    def test_skipped_for_tiny_install(self):
        ctx = RuleContext(job_templates_total=1, surveys_total=0)
        self.assertIsNone(rec_rules.rule_few_surveys(ctx))


class TestRuleTenantNearQuota(unittest.TestCase):
    def test_fires(self):
        ctx = RuleContext(tenant_usage=[('tnt1', 92.0)])
        rec = rec_rules.rule_tenant_near_quota(ctx)
        self.assertIsNotNone(rec)
        self.assertIn('tnt1', rec.why)

    def test_does_not_fire(self):
        ctx = RuleContext(tenant_usage=[('tnt1', 40.0)])
        self.assertIsNone(rec_rules.rule_tenant_near_quota(ctx))


class TestRuleNoCatalogItems(unittest.TestCase):
    def test_fires(self):
        ctx = RuleContext(job_templates_total=3, catalog_items_total=0)
        self.assertIsNotNone(rec_rules.rule_no_catalog_items(ctx))

    def test_does_not_fire(self):
        ctx = RuleContext(job_templates_total=3, catalog_items_total=2)
        self.assertIsNone(rec_rules.rule_no_catalog_items(ctx))


class TestRuleOnlyDefaultTeam(unittest.TestCase):
    def test_fires(self):
        ctx = RuleContext(teams_count=1)
        self.assertIsNotNone(rec_rules.rule_only_default_team(ctx))

    def test_does_not_fire(self):
        ctx = RuleContext(teams_count=3)
        self.assertIsNone(rec_rules.rule_only_default_team(ctx))


class TestRuleDefaultAdminPassword(unittest.TestCase):
    def test_fires(self):
        ctx = RuleContext(admin_default_password=True)
        rec = rec_rules.rule_default_admin_password(ctx)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.severity, SEVERITY_CRITICAL)

    def test_does_not_fire(self):
        ctx = RuleContext(admin_default_password=False)
        self.assertIsNone(rec_rules.rule_default_admin_password(ctx))


# -- Engine / evaluate tests -------------------------------------------------


class TestEvaluate(unittest.TestCase):
    def test_empty_ctx_returns_some_defaults(self):
        # An empty context fires baseline rules (no obs, only default team).
        ctx = RuleContext()
        recs = evaluate('all', ctx)
        # At minimum no_observability and only_default_team fire.
        ids = {r.id for r in recs}
        self.assertIn('no_observability', ids)
        self.assertIn('only_default_team', ids)

    def test_evaluate_returns_empty_when_all_healthy(self):
        ctx = RuleContext(
            otel_enabled=True,
            teams_count=5,
        )
        # Scope filter excludes all rules with no triggers.
        recs = evaluate('compliance', ctx)
        self.assertEqual(recs, [])

    def test_evaluate_sorts_by_severity(self):
        ctx = RuleContext(
            otel_enabled=False,                 # info (dashboard)
            admin_default_password=True,        # critical (dashboard)
            organizations_total=2,              # warn (tenancy)
            tenancy_enabled=False,
            teams_count=5,
        )
        recs = evaluate('all', ctx)
        severities = [r.severity for r in recs]
        # critical must precede warn must precede info.
        crit_idx = severities.index(SEVERITY_CRITICAL)
        warn_idx = severities.index(SEVERITY_WARN)
        info_idx = severities.index(SEVERITY_INFO)
        self.assertLess(crit_idx, warn_idx)
        self.assertLess(warn_idx, info_idx)

    def test_evaluate_filters_by_scope(self):
        ctx = RuleContext(
            otel_enabled=False,
            admin_default_password=True,
            organizations_total=2,
            tenancy_enabled=False,
            teams_count=5,
        )
        recs = evaluate('tenancy', ctx)
        self.assertTrue(all(r.scope == 'tenancy' for r in recs))
        self.assertTrue(any(r.id == 'multi_org_no_tenancy' for r in recs))


if __name__ == '__main__':
    unittest.main()
