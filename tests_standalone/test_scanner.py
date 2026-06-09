"""
Standalone tests for IaC Scanner pure logic.

Covers:
  - severity_at_or_above: the severity ordering matrix
  - effective_enforcement: global kill switch × per-scanner enforcement
  - aggregate_status: no findings / below / at-threshold
  - fail_mode_decision: unavailable × allow|deny
  - applies_to_resource matching
  - Adapter parse_output for ansible-lint / checkov / pip-audit
"""

import os
import sys
import types
import unittest
from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Stub Django before importing the model module
# ---------------------------------------------------------------------------

def _ensure(name):
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)
    return sys.modules[name]


for m in [
    'django', 'django.db', 'django.db.models',
    'django.utils', 'django.utils.translation',
]:
    _ensure(m)

sys.modules['django.utils.translation'].gettext_lazy = lambda s: s


class _Field:
    def __init__(self, *a, **kw):
        pass


class _ForeignKey(_Field):
    pass


_models = sys.modules['django.db.models']
_models.Model = type('Model', (), {'Meta': type('Meta', (), {})})
for cls in [
    'CharField', 'TextField', 'BooleanField', 'JSONField', 'DateTimeField',
    'PositiveIntegerField', 'AutoField', 'IntegerField', 'BinaryField',
    'Index',
]:
    setattr(_models, cls, _Field)
_models.ForeignKey = _ForeignKey
_models.CASCADE = 'CASCADE'
_models.SET_NULL = 'SET_NULL'

_ensure('forail')
_ensure('forail.api')
_ensure('forail.api.versioning')
sys.modules['forail.api.versioning'].reverse = lambda *a, **kw: ''

_ensure('forail.main')
_ensure('forail.main.models')
_base = _ensure('forail.main.models.base')


class _BaseModel:
    class Meta:
        pass


class _CommonModelNameNotUnique:
    name = ''
    description = ''

    class Meta:
        pass


class _CreatedModifiedModel:
    class Meta:
        pass


_base.BaseModel = _BaseModel
_base.CommonModelNameNotUnique = _CommonModelNameNotUnique
_base.CreatedModifiedModel = _CreatedModifiedModel


# Stub the scanning.types module the adapters import.
_ensure('forail.main.scanning')
_types_mod = _ensure('forail.main.scanning.types')


@dataclass
class NormalizedFinding:
    rule_id: str = ''
    severity: str = 'info'
    file_path: str = ''
    line: Optional[int] = None
    message: str = ''


_types_mod.NormalizedFinding = NormalizedFinding


# ---------------------------------------------------------------------------
# Load scanner model
# ---------------------------------------------------------------------------

import importlib.util  # noqa: E402


def _load(mod_name, rel_path):
    path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', rel_path))
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load('scanner_model', 'forail/main/models/scanner.py')

severity_at_or_above = mod.severity_at_or_above
effective_enforcement = mod.effective_enforcement
aggregate_status = mod.aggregate_status
fail_mode_decision = mod.fail_mode_decision
ENFORCEMENT_WARN = mod.ENFORCEMENT_WARN
ENFORCEMENT_ENFORCE = mod.ENFORCEMENT_ENFORCE
STATUS_OK = mod.STATUS_OK
STATUS_WARN = mod.STATUS_WARN
STATUS_BLOCKED = mod.STATUS_BLOCKED

ansible_lint_mod = _load(
    'scanner_ansible_lint', 'forail/main/scanning/tools/ansible_lint.py',
)
checkov_mod = _load('scanner_checkov', 'forail/main/scanning/tools/checkov.py')
pip_audit_mod = _load('scanner_pip_audit', 'forail/main/scanning/tools/pip_audit.py')


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSeverityAtOrAbove(unittest.TestCase):
    def test_critical_beats_all(self):
        for t in ('info', 'low', 'medium', 'high', 'critical'):
            self.assertTrue(severity_at_or_above('critical', t))

    def test_info_only_beats_info(self):
        self.assertTrue(severity_at_or_above('info', 'info'))
        for t in ('low', 'medium', 'high', 'critical'):
            self.assertFalse(severity_at_or_above('info', t))

    def test_medium_exact_threshold(self):
        self.assertTrue(severity_at_or_above('medium', 'medium'))
        self.assertTrue(severity_at_or_above('medium', 'low'))
        self.assertFalse(severity_at_or_above('medium', 'high'))

    def test_high_vs_thresholds(self):
        self.assertTrue(severity_at_or_above('high', 'high'))
        self.assertTrue(severity_at_or_above('high', 'medium'))
        self.assertFalse(severity_at_or_above('high', 'critical'))

    def test_low_vs_thresholds(self):
        self.assertTrue(severity_at_or_above('low', 'info'))
        self.assertTrue(severity_at_or_above('low', 'low'))
        self.assertFalse(severity_at_or_above('low', 'medium'))

    def test_unknown_severity_treated_as_info(self):
        self.assertFalse(severity_at_or_above('bogus', 'low'))
        self.assertTrue(severity_at_or_above('bogus', 'info'))

    def test_case_insensitive(self):
        self.assertTrue(severity_at_or_above('HIGH', 'medium'))
        self.assertTrue(severity_at_or_above('Medium', 'LOW'))


class TestEffectiveEnforcement(unittest.TestCase):
    def test_global_off_returns_none(self):
        self.assertEqual(effective_enforcement(False, ENFORCEMENT_ENFORCE), 'none')
        self.assertEqual(effective_enforcement(False, ENFORCEMENT_WARN), 'none')

    def test_global_on_enforce_passes_through(self):
        self.assertEqual(effective_enforcement(True, ENFORCEMENT_ENFORCE), ENFORCEMENT_ENFORCE)

    def test_global_on_warn_passes_through(self):
        self.assertEqual(effective_enforcement(True, ENFORCEMENT_WARN), ENFORCEMENT_WARN)


class TestAggregateStatus(unittest.TestCase):
    def test_no_findings_is_ok(self):
        self.assertEqual(aggregate_status([], 'high'), STATUS_OK)

    def test_below_threshold_is_warn(self):
        findings = [{'severity': 'low'}, {'severity': 'medium'}]
        self.assertEqual(aggregate_status(findings, 'high'), STATUS_WARN)

    def test_at_threshold_is_blocked(self):
        findings = [{'severity': 'high'}]
        self.assertEqual(aggregate_status(findings, 'high'), STATUS_BLOCKED)

    def test_above_threshold_is_blocked(self):
        findings = [{'severity': 'critical'}]
        self.assertEqual(aggregate_status(findings, 'high'), STATUS_BLOCKED)


class TestFailMode(unittest.TestCase):
    def test_available_always_allows(self):
        self.assertEqual(fail_mode_decision(False, 'allow'), 'allow')
        self.assertEqual(fail_mode_decision(False, 'deny'), 'allow')

    def test_unavailable_allow_mode_allows(self):
        self.assertEqual(fail_mode_decision(True, 'allow'), 'allow')

    def test_unavailable_deny_mode_denies(self):
        self.assertEqual(fail_mode_decision(True, 'deny'), 'deny')


class TestAppliesToResource(unittest.TestCase):
    def setUp(self):
        Scanner = mod.Scanner
        self.s_all = Scanner()
        self.s_all.applies_to = []
        self.s_jt = Scanner()
        self.s_jt.applies_to = ['job_template']
        self.s_multi = Scanner()
        self.s_multi.applies_to = ['job_template', 'ad_hoc_command']

    def test_empty_applies_to_matches_anything(self):
        self.assertTrue(self.s_all.applies_to_resource('job_template'))
        self.assertTrue(self.s_all.applies_to_resource('workflow_job_template'))
        self.assertTrue(self.s_all.applies_to_resource('ad_hoc_command'))

    def test_specific_match(self):
        self.assertTrue(self.s_jt.applies_to_resource('job_template'))
        self.assertFalse(self.s_jt.applies_to_resource('ad_hoc_command'))

    def test_multi_match(self):
        self.assertTrue(self.s_multi.applies_to_resource('job_template'))
        self.assertTrue(self.s_multi.applies_to_resource('ad_hoc_command'))
        self.assertFalse(self.s_multi.applies_to_resource('workflow_job_template'))


class TestAnsibleLintParser(unittest.TestCase):
    SAMPLE = """[
      {
        "type": "issue",
        "check_name": "yaml[line-length]",
        "categories": ["warning"],
        "severity": "warning",
        "message": "Line too long",
        "location": {"path": "play.yml", "lines": {"begin": 12}}
      },
      {
        "type": "issue",
        "check_name": "command-instead-of-shell",
        "categories": ["error"],
        "severity": "error",
        "message": "Use command module",
        "location": {"path": "play.yml", "lines": {"begin": 30}}
      }
    ]"""

    def test_parses_warning_and_error(self):
        findings = ansible_lint_mod.parse_output(self.SAMPLE, '', 2)
        self.assertEqual(len(findings), 2)
        self.assertEqual(findings[0].rule_id, 'yaml[line-length]')
        self.assertEqual(findings[0].severity, 'low')
        self.assertEqual(findings[0].file_path, 'play.yml')
        self.assertEqual(findings[0].line, 12)
        self.assertEqual(findings[1].severity, 'high')
        self.assertEqual(findings[1].line, 30)
        self.assertEqual(findings[1].rule_id, 'command-instead-of-shell')

    def test_empty_stdout_returns_empty(self):
        self.assertEqual(ansible_lint_mod.parse_output('', '', 0), [])

    def test_invalid_json_returns_empty(self):
        self.assertEqual(ansible_lint_mod.parse_output('not json', '', 0), [])

    def test_build_command_includes_target(self):
        cmd = ansible_lint_mod.build_command('/tmp/play.yml', {})
        self.assertIn('ansible-lint', cmd)
        self.assertIn('/tmp/play.yml', cmd)
        self.assertIn('-f', cmd)
        self.assertIn('json', cmd)


class TestCheckovParser(unittest.TestCase):
    SAMPLE = """{
      "results": {
        "failed_checks": [
          {"check_id": "CKV_ANSIBLE_1",
           "check_name": "Ensure no plaintext secrets",
           "file_path": "play.yml",
           "file_line_range": [15, 18],
           "severity": "HIGH"}
        ],
        "passed_checks": [
          {"check_id": "CKV_ANSIBLE_2", "check_name": "Passed one"}
        ]
      }
    }"""

    def test_only_failed_checks_emit_findings(self):
        findings = checkov_mod.parse_output(self.SAMPLE, '', 1)
        self.assertEqual(len(findings), 1)
        f = findings[0]
        self.assertEqual(f.rule_id, 'CKV_ANSIBLE_1')
        self.assertEqual(f.severity, 'high')
        self.assertEqual(f.file_path, 'play.yml')
        self.assertEqual(f.line, 15)
        self.assertIn('plaintext', f.message)

    def test_severity_default_when_missing(self):
        sample = """{"results": {"failed_checks": [
            {"check_id": "CKV_X", "check_name": "x", "file_path": "a.yml"}
        ]}}"""
        findings = checkov_mod.parse_output(sample, '', 1)
        self.assertEqual(findings[0].severity, 'medium')

    def test_empty_returns_empty(self):
        self.assertEqual(checkov_mod.parse_output('', '', 0), [])


class TestPipAuditParser(unittest.TestCase):
    SAMPLE = """{
      "dependencies": [
        {"name": "urllib3", "version": "1.26.4",
         "vulns": [
           {"id": "GHSA-xxxx-yyyy-zzzz",
            "fix_versions": ["1.26.5"],
            "description": "CRLF injection"}
         ]},
        {"name": "requests", "version": "2.32.0", "vulns": []}
      ]
    }"""

    def test_parses_single_cve(self):
        findings = pip_audit_mod.parse_output(self.SAMPLE, '', 1)
        self.assertEqual(len(findings), 1)
        f = findings[0]
        self.assertEqual(f.rule_id, 'GHSA-xxxx-yyyy-zzzz')
        self.assertEqual(f.severity, 'high')
        self.assertEqual(f.file_path, 'urllib3')
        self.assertIn('CRLF', f.message)
        self.assertIn('1.26.5', f.message)

    def test_empty_returns_empty(self):
        self.assertEqual(pip_audit_mod.parse_output('', '', 0), [])

    def test_no_vulns_no_findings(self):
        sample = '{"dependencies": [{"name": "foo", "version": "1.0", "vulns": []}]}'
        self.assertEqual(pip_audit_mod.parse_output(sample, '', 0), [])


if __name__ == '__main__':
    unittest.main()
