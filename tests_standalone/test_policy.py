"""
Standalone tests for Policy-as-Code pure logic.

Covers:
  - effective_enforcement: kill switch + org override + policy mode matrix
  - fail_mode_decision: OPA-down behavior
  - parse_decision: all OPA result shapes (bool / str / list / dict)
  - applies_to_resource matching
"""

import os
import sys
import types
import unittest


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


class _CommonModelNameNotUnique:
    name = ''
    description = ''

    class Meta:
        pass


class _CreatedModifiedModel:
    class Meta:
        pass


_base.CommonModelNameNotUnique = _CommonModelNameNotUnique
_base.CreatedModifiedModel = _CreatedModifiedModel


# ---------------------------------------------------------------------------
# Load policy model
# ---------------------------------------------------------------------------

import importlib.util  # noqa: E402

_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'forail', 'main', 'models', 'policy.py')
)
spec = importlib.util.spec_from_file_location('policy_model', _path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

effective_enforcement = mod.effective_enforcement
fail_mode_decision = mod.fail_mode_decision
ENFORCEMENT_NONE = mod.ENFORCEMENT_NONE
ENFORCEMENT_WARN = mod.ENFORCEMENT_WARN
ENFORCEMENT_ENFORCE = mod.ENFORCEMENT_ENFORCE


# ---------------------------------------------------------------------------
# Also load opa_client for parse_decision
# ---------------------------------------------------------------------------

_opa_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'forail', 'main', 'policy', 'opa_client.py')
)
spec2 = importlib.util.spec_from_file_location('opa_client', _opa_path)
opa_mod = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(opa_mod)
parse_decision = opa_mod.parse_decision


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEffectiveEnforcement(unittest.TestCase):
    def test_global_off_always_none(self):
        for org in (ENFORCEMENT_NONE, ENFORCEMENT_WARN, ENFORCEMENT_ENFORCE):
            for pol in (ENFORCEMENT_WARN, ENFORCEMENT_ENFORCE):
                self.assertEqual(effective_enforcement(False, org, pol), ENFORCEMENT_NONE)

    def test_org_none_always_none(self):
        self.assertEqual(effective_enforcement(True, ENFORCEMENT_NONE, ENFORCEMENT_ENFORCE), ENFORCEMENT_NONE)

    def test_org_warn_caps_to_warn(self):
        self.assertEqual(effective_enforcement(True, ENFORCEMENT_WARN, ENFORCEMENT_ENFORCE), ENFORCEMENT_WARN)
        self.assertEqual(effective_enforcement(True, ENFORCEMENT_WARN, ENFORCEMENT_WARN), ENFORCEMENT_WARN)

    def test_org_enforce_passes_through_policy(self):
        self.assertEqual(effective_enforcement(True, ENFORCEMENT_ENFORCE, ENFORCEMENT_WARN), ENFORCEMENT_WARN)
        self.assertEqual(effective_enforcement(True, ENFORCEMENT_ENFORCE, ENFORCEMENT_ENFORCE), ENFORCEMENT_ENFORCE)


class TestFailMode(unittest.TestCase):
    def test_opa_up_always_allow(self):
        self.assertEqual(fail_mode_decision(False, 'allow'), 'allow')
        self.assertEqual(fail_mode_decision(False, 'deny'), 'allow')

    def test_opa_down_allow_mode_allows(self):
        self.assertEqual(fail_mode_decision(True, 'allow'), 'allow')

    def test_opa_down_deny_mode_denies(self):
        self.assertEqual(fail_mode_decision(True, 'deny'), 'deny')


class TestParseDecisionDict(unittest.TestCase):
    def test_empty(self):
        warns, denies = parse_decision({})
        self.assertEqual(warns, [])
        self.assertEqual(denies, [])

    def test_dict_warn_and_deny_lists(self):
        warns, denies = parse_decision({
            'warn': ['Heads up'],
            'deny': ['Blocked because reasons'],
        })
        self.assertEqual(warns, ['Heads up'])
        self.assertEqual(denies, ['Blocked because reasons'])

    def test_violations_with_severity(self):
        warns, denies = parse_decision({
            'violations': [
                {'severity': 'warn', 'message': 'soft'},
                {'severity': 'deny', 'message': 'hard'},
            ],
        })
        self.assertEqual(warns, ['soft'])
        self.assertEqual(denies, ['hard'])

    def test_dict_deny_bool(self):
        warns, denies = parse_decision({'deny': True})
        self.assertEqual(denies, ['Policy denied launch.'])


class TestParseDecisionScalars(unittest.TestCase):
    def test_bool_true_denies(self):
        _, denies = parse_decision(True)
        self.assertEqual(denies, ['Policy denied launch.'])

    def test_bool_false_allows(self):
        warns, denies = parse_decision(False)
        self.assertEqual(warns, [])
        self.assertEqual(denies, [])

    def test_string_is_deny_message(self):
        _, denies = parse_decision('Out of hours')
        self.assertEqual(denies, ['Out of hours'])

    def test_list_of_strings_is_denies(self):
        _, denies = parse_decision(['a', 'b'])
        self.assertEqual(denies, ['a', 'b'])


class TestAppliesToResource(unittest.TestCase):
    def setUp(self):
        Policy = mod.Policy
        self.p_all = Policy()
        self.p_all.applies_to = []
        self.p_jt = Policy()
        self.p_jt.applies_to = ['job_template']
        self.p_jt_wf = Policy()
        self.p_jt_wf.applies_to = ['job_template', 'workflow_job_template']

    def test_empty_applies_to_matches_anything(self):
        self.assertTrue(self.p_all.applies_to_resource('job_template'))
        self.assertTrue(self.p_all.applies_to_resource('ad_hoc_command'))
        self.assertTrue(self.p_all.applies_to_resource('workflow_job_template'))

    def test_specific_match(self):
        self.assertTrue(self.p_jt.applies_to_resource('job_template'))
        self.assertFalse(self.p_jt.applies_to_resource('ad_hoc_command'))

    def test_multi_match(self):
        self.assertTrue(self.p_jt_wf.applies_to_resource('job_template'))
        self.assertTrue(self.p_jt_wf.applies_to_resource('workflow_job_template'))
        self.assertFalse(self.p_jt_wf.applies_to_resource('ad_hoc_command'))


class TestEnforcementMatrix(unittest.TestCase):
    """Cross-product matrix to make sure the resolver is exhaustive."""

    def test_full_matrix(self):
        cases = [
            # (global, org, policy, expected)
            (False, ENFORCEMENT_ENFORCE, ENFORCEMENT_ENFORCE, ENFORCEMENT_NONE),
            (True,  ENFORCEMENT_NONE,    ENFORCEMENT_ENFORCE, ENFORCEMENT_NONE),
            (True,  ENFORCEMENT_WARN,    ENFORCEMENT_WARN,    ENFORCEMENT_WARN),
            (True,  ENFORCEMENT_WARN,    ENFORCEMENT_ENFORCE, ENFORCEMENT_WARN),
            (True,  ENFORCEMENT_ENFORCE, ENFORCEMENT_WARN,    ENFORCEMENT_WARN),
            (True,  ENFORCEMENT_ENFORCE, ENFORCEMENT_ENFORCE, ENFORCEMENT_ENFORCE),
        ]
        for g, o, p, expected in cases:
            with self.subTest(global_=g, org=o, policy=p):
                self.assertEqual(effective_enforcement(g, o, p), expected)


if __name__ == '__main__':
    unittest.main()
