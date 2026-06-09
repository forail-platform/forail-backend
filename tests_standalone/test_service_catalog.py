"""
Standalone tests for Self-Service Portal lifecycle logic.

These tests exercise the ServiceRequest state machine (submit / approve /
reject / sync) using lightweight fakes that mimic the model surface, so we
can run without spinning up Django. The same logic lives in
forail/main/models/service_catalog.py.
"""

import sys
import os
import types
import unittest
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Stub Django before importing the model module
# ---------------------------------------------------------------------------

def _ensure_module(name):
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)
    return sys.modules[name]


for mod_name in [
    'django', 'django.core', 'django.core.exceptions',
    'django.db', 'django.db.models', 'django.db.models.signals',
    'django.dispatch',
    'django.utils', 'django.utils.translation', 'django.utils.timezone',
]:
    _ensure_module(mod_name)


# Minimal Django shims used at import time of service_catalog.py
class _ValidationError(Exception):
    pass


sys.modules['django.core.exceptions'].ValidationError = _ValidationError
sys.modules['django.utils.timezone'].now = lambda: datetime.now(timezone.utc)
sys.modules['django.utils.translation'].gettext_lazy = lambda s: s


class _Field:
    def __init__(self, *a, **kw):
        pass


class _ForeignKey(_Field):
    pass


class _Meta:
    pass


_models = sys.modules['django.db.models']
_models.Model = type('Model', (), {'Meta': _Meta})
for cls_name in [
    'CharField', 'TextField', 'BooleanField', 'JSONField', 'DateTimeField',
    'PositiveIntegerField', 'AutoField', 'IntegerField',
]:
    setattr(_models, cls_name, _Field)
_models.ForeignKey = _ForeignKey
_models.Index = _Field
_models.F = lambda x: x
_models.CASCADE = 'CASCADE'
_models.SET_NULL = 'SET_NULL'
_models.PROTECT = 'PROTECT'


class _Signal:
    def connect(self, *a, **kw):
        pass


sys.modules['django.db.models.signals'].post_save = _Signal()
sys.modules['django.dispatch'].receiver = lambda *a, **kw: (lambda f: f)


# Stub forail.api.versioning.reverse and the base classes
_ensure_module('forail')
_ensure_module('forail.api')
_ensure_module('forail.api.versioning')
sys.modules['forail.api.versioning'].reverse = lambda *a, **kw: ''

_ensure_module('forail.main')
_ensure_module('forail.main.models')
_base = _ensure_module('forail.main.models.base')


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

# We don't import the unified_jobs module, so the post_save handler's
# isinstance check will gracefully short-circuit during these tests.
_ensure_module('forail.main.models.unified_jobs')
sys.modules['forail.main.models.unified_jobs'].UnifiedJob = type('UnifiedJob', (), {})


# ---------------------------------------------------------------------------
# Now load the model module
# ---------------------------------------------------------------------------

import importlib.util  # noqa: E402

_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'forail', 'main', 'models', 'service_catalog.py')
)
spec = importlib.util.spec_from_file_location('service_catalog', _path)
service_catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service_catalog)

ServiceRequest = service_catalog.ServiceRequest
ServiceCatalogItem = service_catalog.ServiceCatalogItem


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeRole:
    def __init__(self, members=()):
        self._members = list(members)

    @property
    def members(self):
        outer = self

        class _M:
            def filter(self, **kw):
                pk = kw.get('pk')
                matched = [m for m in outer._members if getattr(m, 'pk', None) == pk]

                class _Q:
                    def exists(_self):
                        return bool(matched)

                return _Q()

        return _M()


class FakeOrg:
    def __init__(self, admins=()):
        self.admin_role = FakeRole(admins)


class FakeTeam:
    def __init__(self, members=()):
        self.member_role = FakeRole(members)


class FakeUser:
    def __init__(self, pk, is_superuser=False, is_authenticated=True):
        self.pk = pk
        self.id = pk
        self.is_superuser = is_superuser
        self.is_authenticated = is_authenticated


class FakeUnifiedJob:
    def __init__(self, status='pending'):
        self.status = status
        self.signal_started = False

    def signal_start(self):
        self.signal_started = True


class FakeTemplate:
    def __init__(self, fail=False):
        self.fail = fail
        self.last_kwargs = None

    def create_unified_job(self, **kwargs):
        self.last_kwargs = kwargs
        if self.fail:
            return None
        return FakeUnifiedJob(status='pending')


class FakeCatalogItem:
    def __init__(self, requires_approval=False, organization=None,
                 approver_team=None, template=None, is_workflow=False):
        self.requires_approval = requires_approval
        self.organization = organization
        self.approver_team = approver_team
        self.underlying_template = template
        self.is_workflow = is_workflow


class FakeServiceRequest:
    """A duck-typed object that we can run real ServiceRequest methods on."""
    TERMINAL_STATUSES = ServiceRequest.TERMINAL_STATUSES

    def __init__(self, catalog_item, requested_by, extra_vars=None,
                 node_survey_data=None, status='pending_approval',
                 unified_job=None):
        self.pk = 1
        self.catalog_item = catalog_item
        self.requested_by = requested_by
        self.extra_vars = extra_vars or {}
        self.node_survey_data = node_survey_data or {}
        self.status = status
        self.approved_by = None
        self.approved_at = None
        self.rejection_reason = ''
        self.unified_job = unified_job
        self.modified = None

    def save(self, update_fields=None):
        pass

    # Bind the real methods from ServiceRequest
    submit = ServiceRequest.submit
    approve = ServiceRequest.approve
    reject = ServiceRequest.reject
    can_user_approve = ServiceRequest.can_user_approve
    _launch = ServiceRequest._launch
    sync_status_from_job = ServiceRequest.sync_status_from_job


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSubmit(unittest.TestCase):
    def test_submit_with_approval_stays_pending(self):
        item = FakeCatalogItem(requires_approval=True, template=FakeTemplate())
        sr = FakeServiceRequest(item, FakeUser(1))
        sr.submit()
        self.assertEqual(sr.status, 'pending_approval')
        self.assertIsNone(sr.unified_job)

    def test_submit_without_approval_auto_launches(self):
        tpl = FakeTemplate()
        item = FakeCatalogItem(requires_approval=False, template=tpl)
        sr = FakeServiceRequest(item, FakeUser(1), extra_vars={'k': 'v'})
        sr.submit()
        self.assertEqual(sr.status, 'running')
        self.assertIsNotNone(sr.unified_job)
        self.assertTrue(sr.unified_job.signal_started)
        self.assertEqual(tpl.last_kwargs['extra_vars'], {'k': 'v'})

    def test_submit_launch_failure_sets_failed(self):
        item = FakeCatalogItem(requires_approval=False, template=FakeTemplate(fail=True))
        sr = FakeServiceRequest(item, FakeUser(1))
        sr.submit()
        self.assertEqual(sr.status, 'failed')


class TestApproverPermission(unittest.TestCase):
    def test_superuser_can_approve(self):
        item = FakeCatalogItem(requires_approval=True, organization=FakeOrg())
        sr = FakeServiceRequest(item, FakeUser(1))
        self.assertTrue(sr.can_user_approve(FakeUser(99, is_superuser=True)))

    def test_team_member_can_approve(self):
        u = FakeUser(2)
        team = FakeTeam(members=[u])
        item = FakeCatalogItem(requires_approval=True, approver_team=team)
        sr = FakeServiceRequest(item, FakeUser(1))
        self.assertTrue(sr.can_user_approve(u))

    def test_non_team_member_cannot_approve(self):
        team = FakeTeam(members=[FakeUser(2)])
        item = FakeCatalogItem(requires_approval=True, approver_team=team)
        sr = FakeServiceRequest(item, FakeUser(1))
        self.assertFalse(sr.can_user_approve(FakeUser(3)))

    def test_org_admin_fallback_when_no_team(self):
        admin = FakeUser(5)
        item = FakeCatalogItem(requires_approval=True, organization=FakeOrg(admins=[admin]))
        sr = FakeServiceRequest(item, FakeUser(1))
        self.assertTrue(sr.can_user_approve(admin))

    def test_unauthenticated_cannot_approve(self):
        item = FakeCatalogItem(requires_approval=True, organization=FakeOrg())
        sr = FakeServiceRequest(item, FakeUser(1))
        self.assertFalse(sr.can_user_approve(FakeUser(2, is_authenticated=False)))


class TestApproveReject(unittest.TestCase):
    def test_approve_launches(self):
        tpl = FakeTemplate()
        admin = FakeUser(5)
        item = FakeCatalogItem(
            requires_approval=True,
            organization=FakeOrg(admins=[admin]),
            template=tpl,
        )
        sr = FakeServiceRequest(item, FakeUser(1))
        sr.approve(admin)
        self.assertEqual(sr.status, 'running')
        self.assertEqual(sr.approved_by, admin)
        self.assertIsNotNone(sr.unified_job)

    def test_approve_by_unauthorized_raises(self):
        item = FakeCatalogItem(requires_approval=True, organization=FakeOrg())
        sr = FakeServiceRequest(item, FakeUser(1))
        with self.assertRaises(_ValidationError):
            sr.approve(FakeUser(2))

    def test_approve_terminal_state_raises(self):
        item = FakeCatalogItem(requires_approval=True, organization=FakeOrg())
        sr = FakeServiceRequest(item, FakeUser(1), status='running')
        with self.assertRaises(_ValidationError):
            sr.approve(FakeUser(99, is_superuser=True))

    def test_reject_sets_state(self):
        admin = FakeUser(5)
        item = FakeCatalogItem(requires_approval=True, organization=FakeOrg(admins=[admin]))
        sr = FakeServiceRequest(item, FakeUser(1))
        sr.reject(admin, reason='not now')
        self.assertEqual(sr.status, 'rejected')
        self.assertEqual(sr.rejection_reason, 'not now')

    def test_reject_by_unauthorized_raises(self):
        item = FakeCatalogItem(requires_approval=True, organization=FakeOrg())
        sr = FakeServiceRequest(item, FakeUser(1))
        with self.assertRaises(_ValidationError):
            sr.reject(FakeUser(2), reason='no')


class TestSyncStatus(unittest.TestCase):
    def _make_running(self, uj_status):
        item = FakeCatalogItem(requires_approval=False, template=FakeTemplate())
        sr = FakeServiceRequest(item, FakeUser(1), status='running',
                                unified_job=FakeUnifiedJob(status=uj_status))
        return sr

    def test_sync_successful(self):
        sr = self._make_running('successful')
        sr.sync_status_from_job()
        self.assertEqual(sr.status, 'successful')

    def test_sync_failed(self):
        sr = self._make_running('failed')
        sr.sync_status_from_job()
        self.assertEqual(sr.status, 'failed')

    def test_sync_error_maps_to_failed(self):
        sr = self._make_running('error')
        sr.sync_status_from_job()
        self.assertEqual(sr.status, 'failed')

    def test_sync_canceled(self):
        sr = self._make_running('canceled')
        sr.sync_status_from_job()
        self.assertEqual(sr.status, 'canceled')

    def test_sync_no_op_for_terminal(self):
        item = FakeCatalogItem(requires_approval=False, template=FakeTemplate())
        sr = FakeServiceRequest(item, FakeUser(1), status='successful',
                                unified_job=FakeUnifiedJob(status='failed'))
        sr.sync_status_from_job()
        self.assertEqual(sr.status, 'successful')

    def test_sync_no_op_when_no_uj(self):
        item = FakeCatalogItem(requires_approval=False, template=FakeTemplate())
        sr = FakeServiceRequest(item, FakeUser(1), status='running')
        sr.sync_status_from_job()
        self.assertEqual(sr.status, 'running')

    def test_sync_intermediate_status_no_change(self):
        sr = self._make_running('pending')
        sr.sync_status_from_job()
        self.assertEqual(sr.status, 'running')


class TestNodeSurveyData(unittest.TestCase):
    def test_workflow_passes_node_survey_data(self):
        tpl = FakeTemplate()
        item = FakeCatalogItem(
            requires_approval=False, template=tpl, is_workflow=True,
        )
        sr = FakeServiceRequest(
            item, FakeUser(1),
            extra_vars={'a': 1},
            node_survey_data={'node_a': {'q': 'v'}},
        )
        sr.submit()
        self.assertEqual(tpl.last_kwargs['node_survey_data'], {'node_a': {'q': 'v'}})

    def test_non_workflow_omits_node_survey_data(self):
        tpl = FakeTemplate()
        item = FakeCatalogItem(requires_approval=False, template=tpl, is_workflow=False)
        sr = FakeServiceRequest(item, FakeUser(1), node_survey_data={'x': {}})
        sr.submit()
        self.assertNotIn('node_survey_data', tpl.last_kwargs)


if __name__ == '__main__':
    unittest.main()
