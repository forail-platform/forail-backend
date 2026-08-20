"""Standalone tests for the tenant isolation middleware.

Loads forail/main/tenancy/isolation.py directly with Django and the RLS module
stubbed -- no database, no settings module. The point of interest is what the
middleware does when it *cannot* determine a request's tenant: RLS reads an
unset tenant id as "every row", so the difference between "this user has no
tenant" and "the lookup failed" is the difference between a scoped request and
a global one.
"""

import importlib.util
import os
import sys
import types
import unittest
from unittest.mock import MagicMock


def _load(mod_name, rel_path):
    path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', rel_path))
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


class _Settings:
    """Stands in for django.conf.settings; only the flags read here matter."""

    def __init__(self, **flags):
        self.__dict__.update(flags)


class _JsonResponse:
    """Records what the middleware answered instead of running the view."""

    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status


settings_holder = _Settings()

django = types.ModuleType('django')
django_conf = types.ModuleType('django.conf')
django_conf.settings = settings_holder
django_http = types.ModuleType('django.http')
django_http.JsonResponse = _JsonResponse
sys.modules.setdefault('django', django)
sys.modules['django.conf'] = django_conf
sys.modules['django.http'] = django_http

# The RLS module talks to Postgres; the middleware only needs the two calls.
set_tenant_id = MagicMock()
clear_tenant_id = MagicMock()
rls = types.ModuleType('forail.main.tenancy.rls')
rls.set_tenant_id = set_tenant_id
rls.clear_tenant_id = clear_tenant_id

for pkg in ('forail', 'forail.main', 'forail.main.tenancy'):
    sys.modules.setdefault(pkg, types.ModuleType(pkg))
sys.modules['forail.main.tenancy.rls'] = rls
_load('forail.main.tenancy.helpers', 'forail/main/tenancy/helpers.py')

isolation = _load('forail.main.tenancy.isolation', 'forail/main/tenancy/isolation.py')
TenantIsolationMiddleware = isolation.TenantIsolationMiddleware


def tenant_user(is_superuser=False):
    user = MagicMock()
    user.is_authenticated = True
    user.is_superuser = is_superuser
    return user


def request_for(user):
    request = MagicMock()
    request.user = user
    request.path = '/api/v2/job_templates/'
    return request


class TenantResolutionFailure(unittest.TestCase):
    """H3: a failed lookup must not read as 'this user has no tenant'."""

    def setUp(self):
        set_tenant_id.reset_mock()
        clear_tenant_id.reset_mock()
        settings_holder.__dict__.clear()
        settings_holder.TENANCY_ENABLED = True
        settings_holder.TENANCY_RLS_ENABLED = True
        self.view = MagicMock(return_value='view-response')
        self.mw = TenantIsolationMiddleware(self.view)

    def _fail_resolution(self):
        self.mw._resolve_tenant_org = MagicMock(side_effect=RuntimeError('database is down'))

    def test_failed_lookup_does_not_run_the_view(self):
        self._fail_resolution()
        response = self.mw(request_for(tenant_user()))
        self.assertEqual(response.status_code, 500)
        self.view.assert_not_called()

    def test_failed_lookup_never_installs_a_scope(self):
        self._fail_resolution()
        self.mw(request_for(tenant_user()))
        set_tenant_id.assert_not_called()

    def test_failed_lookup_is_ignored_when_tenancy_is_off(self):
        # A single-tenant install has no scope to lose, and must not start
        # answering 500 because of this gate.
        settings_holder.TENANCY_ENABLED = False
        self._fail_resolution()
        self.assertEqual(self.mw(request_for(tenant_user())), 'view-response')

    def test_failed_lookup_is_ignored_when_rls_is_off(self):
        settings_holder.TENANCY_RLS_ENABLED = False
        self._fail_resolution()
        self.assertEqual(self.mw(request_for(tenant_user())), 'view-response')

    def test_resolver_lets_a_database_error_out(self):
        # The middleware can only fail closed if the lookup stops swallowing.
        user = tenant_user()
        user.organizations.filter.side_effect = RuntimeError('database is down')
        request = request_for(user)
        with self.assertRaises(RuntimeError):
            TenantIsolationMiddleware._resolve_tenant_org(request)


class TenantResolutionSuccess(unittest.TestCase):
    """The paths that must keep working unchanged."""

    def setUp(self):
        set_tenant_id.reset_mock()
        clear_tenant_id.reset_mock()
        settings_holder.__dict__.clear()
        settings_holder.TENANCY_ENABLED = True
        settings_holder.TENANCY_RLS_ENABLED = True
        self.view = MagicMock(return_value='view-response')
        self.mw = TenantIsolationMiddleware(self.view)

    def test_resolved_org_scopes_the_request(self):
        org = MagicMock(pk=42)
        self.mw._resolve_tenant_org = MagicMock(return_value=org)
        request = request_for(tenant_user())
        self.assertEqual(self.mw(request), 'view-response')
        set_tenant_id.assert_called_once_with(42)
        clear_tenant_id.assert_called_once()
        self.assertIs(request._tenant_org, org)

    def test_no_tenant_org_runs_unscoped(self):
        # A superuser or a non-tenant user legitimately has no scope.
        self.mw._resolve_tenant_org = MagicMock(return_value=None)
        self.assertEqual(self.mw(request_for(tenant_user(is_superuser=True))), 'view-response')
        set_tenant_id.assert_not_called()

    def test_set_tenant_id_failure_still_fails_closed(self):
        # Pre-existing behaviour, kept under test alongside the new path.
        self.mw._resolve_tenant_org = MagicMock(return_value=MagicMock(pk=7))
        set_tenant_id.side_effect = RuntimeError('cannot set session variable')
        try:
            response = self.mw(request_for(tenant_user()))
        finally:
            set_tenant_id.side_effect = None
        self.assertEqual(response.status_code, 500)
        self.view.assert_not_called()

    def test_superuser_resolver_returns_none_without_a_query(self):
        user = tenant_user(is_superuser=True)
        self.assertIsNone(TenantIsolationMiddleware._resolve_tenant_org(request_for(user)))
        user.organizations.filter.assert_not_called()

    def test_resolver_returns_none_when_tenancy_is_off(self):
        settings_holder.TENANCY_ENABLED = False
        user = tenant_user()
        self.assertIsNone(TenantIsolationMiddleware._resolve_tenant_org(request_for(user)))
        user.organizations.filter.assert_not_called()


if __name__ == '__main__':
    unittest.main()
