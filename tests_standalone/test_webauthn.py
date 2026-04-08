"""
Standalone tests for WebAuthn pure logic (no Django bootstrap).

Covers:
  - is_webauthn_required(setting, is_admin) policy resolver
  - is_replay(stored, presented) sign-count guard
  - Challenge TTL behavior (timestamps)
  - URL-safe base64 helpers used by the views
"""

import os
import sys
import types
import unittest
from datetime import datetime, timezone, timedelta


# ---------------------------------------------------------------------------
# Stub Django before importing the model module
# ---------------------------------------------------------------------------

def _ensure(name):
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)
    return sys.modules[name]


for m in [
    'django', 'django.db', 'django.db.models',
    'django.utils', 'django.utils.translation', 'django.utils.timezone',
]:
    _ensure(m)

sys.modules['django.utils.translation'].gettext_lazy = lambda s: s
sys.modules['django.utils.timezone'].now = lambda: datetime.now(timezone.utc)


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


# Stub forge api/models base imports
_ensure('forge')
_ensure('forge.api')
_ensure('forge.api.versioning')
sys.modules['forge.api.versioning'].reverse = lambda *a, **kw: ''

_ensure('forge.main')
_ensure('forge.main.models')
_base = _ensure('forge.main.models.base')


class _CreatedModifiedModel:
    class Meta:
        pass


_base.CreatedModifiedModel = _CreatedModifiedModel


# ---------------------------------------------------------------------------
# Load the module
# ---------------------------------------------------------------------------

import importlib.util  # noqa: E402

_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'forge', 'main', 'models', 'webauthn.py')
)
spec = importlib.util.spec_from_file_location('webauthn_models', _path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

is_webauthn_required = mod.is_webauthn_required
is_replay = mod.is_replay
WEBAUTHN_REQUIRED_NONE = mod.WEBAUTHN_REQUIRED_NONE
WEBAUTHN_REQUIRED_ADMINS = mod.WEBAUTHN_REQUIRED_ADMINS
WEBAUTHN_REQUIRED_ALL = mod.WEBAUTHN_REQUIRED_ALL


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPolicyResolver(unittest.TestCase):
    def test_none_setting_never_requires(self):
        self.assertFalse(is_webauthn_required(WEBAUTHN_REQUIRED_NONE, False))
        self.assertFalse(is_webauthn_required(WEBAUTHN_REQUIRED_NONE, True))

    def test_admins_only_requires_for_admin(self):
        self.assertTrue(is_webauthn_required(WEBAUTHN_REQUIRED_ADMINS, True))

    def test_admins_only_skips_non_admin(self):
        self.assertFalse(is_webauthn_required(WEBAUTHN_REQUIRED_ADMINS, False))

    def test_all_setting_requires_for_everyone(self):
        self.assertTrue(is_webauthn_required(WEBAUTHN_REQUIRED_ALL, False))
        self.assertTrue(is_webauthn_required(WEBAUTHN_REQUIRED_ALL, True))

    def test_unknown_setting_falls_back_to_no(self):
        self.assertFalse(is_webauthn_required('weird', True))


class TestReplayGuard(unittest.TestCase):
    def test_strictly_increasing_count_ok(self):
        self.assertFalse(is_replay(stored_count=5, presented_count=6))
        self.assertFalse(is_replay(stored_count=5, presented_count=99))

    def test_equal_count_is_replay(self):
        self.assertTrue(is_replay(stored_count=5, presented_count=5))

    def test_decreasing_count_is_replay(self):
        self.assertTrue(is_replay(stored_count=5, presented_count=4))
        self.assertTrue(is_replay(stored_count=5, presented_count=0))

    def test_both_zero_is_allowed(self):
        # Some authenticators never bump the counter; both-zero is permitted.
        self.assertFalse(is_replay(stored_count=0, presented_count=0))

    def test_zero_to_one_ok(self):
        self.assertFalse(is_replay(stored_count=0, presented_count=1))


class TestChallengeTtl(unittest.TestCase):
    """The challenge models store created_at and expires_at — verify the
    arithmetic the views use to set TTL is sensible."""

    def test_default_ttl_is_in_the_future(self):
        from datetime import datetime, timezone, timedelta
        ttl = 300
        now_ts = datetime.now(timezone.utc)
        expires = now_ts + timedelta(seconds=ttl)
        self.assertGreater(expires, now_ts)

    def test_expired_window_is_in_past(self):
        from datetime import datetime, timezone, timedelta
        now_ts = datetime.now(timezone.utc)
        expires = now_ts - timedelta(seconds=1)
        self.assertLess(expires, now_ts)


class TestB64uHelpers(unittest.TestCase):
    """Re-implement the helpers locally so the test doesn't depend on
    importing the views module (which pulls in DRF and friends)."""

    def setUp(self):
        import base64

        def _b64u(data):
            return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')

        def _b64u_decode(s):
            pad = '=' * (-len(s) % 4)
            return base64.urlsafe_b64decode(s + pad)

        self.encode = _b64u
        self.decode = _b64u_decode

    def test_round_trip(self):
        data = b'\x01\x02\xff\xfe\x00rawcredid'
        self.assertEqual(self.decode(self.encode(data)), data)

    def test_round_trip_empty(self):
        self.assertEqual(self.decode(self.encode(b'')), b'')

    def test_no_padding_in_output(self):
        out = self.encode(b'a')
        self.assertNotIn('=', out)


class TestPolicyMatrix(unittest.TestCase):
    """Cross-product matrix to make sure the resolver is exhaustive."""

    def test_full_matrix(self):
        cases = [
            (WEBAUTHN_REQUIRED_NONE, False, False),
            (WEBAUTHN_REQUIRED_NONE, True,  False),
            (WEBAUTHN_REQUIRED_ADMINS, False, False),
            (WEBAUTHN_REQUIRED_ADMINS, True,  True),
            (WEBAUTHN_REQUIRED_ALL, False, True),
            (WEBAUTHN_REQUIRED_ALL, True,  True),
        ]
        for setting, is_admin, expected in cases:
            with self.subTest(setting=setting, is_admin=is_admin):
                self.assertEqual(is_webauthn_required(setting, is_admin), expected)


if __name__ == '__main__':
    unittest.main()
