"""Monitored servers: model, RBAC and API (forail-backend#17, forail-mobile#52).

The cast follows the epic's "done when": users A and B in organization 1,
C in organization 2, D an admin of organization 1 who is not a superuser.
A registers a server. A and D see it; B and C get 404 everywhere; the
superuser sees everything; D grants B read access and takes it back. The
Forail Mobile backend is replaced by a fake that records what it was asked.
"""

import uuid

import pytest
from ansible_base.rbac.models import RoleDefinition
from crum import impersonate
from django.contrib.auth.models import User
from django.test import override_settings
from rest_framework.exceptions import PermissionDenied

from forail.main.access.monitored_servers import MonitoredServerAccess
from forail.main.models import ActivityStream, Organization
from forail.main.models.monitored_server import MonitoredServer
from forail.main.services import forail_mobile
from forail.main.services.forail_mobile import EnrollmentCode, ServerStatus

pytestmark = pytest.mark.django_db

SERVICE_TOKEN = 'test-service-token'


class FakeMobile:
    """Stands in for the Forail Mobile service API."""

    def __init__(self):
        self.calls = []
        self.store = {}
        self.unavailable = False
        self.conflict = False
        self.legacy = []

    def __call__(self, *args, **kwargs):
        return self  # used as the client class

    def _check(self):
        if self.unavailable:
            raise forail_mobile.MobileUnavailable('down')

    def create_server(self, name, organization_id, owner_id):
        self._check()
        if self.conflict:
            raise forail_mobile.MobileConflict('exists')
        server_id = str(uuid.uuid4())
        self.store[server_id] = {'name': name, 'organization': str(organization_id), 'owner': str(owner_id)}
        self.calls.append(('create', name, str(organization_id), str(owner_id)))
        return server_id

    def enrollment_code(self, server_id, issued_by=None):
        self._check()
        self.calls.append(('enrollment_code', str(server_id), issued_by))
        return EnrollmentCode(code='fme_onetime', expires_at='2026-11-01T10:10:00Z')

    def rotate(self, server_id, issued_by=None):
        self._check()
        self.calls.append(('rotate', str(server_id), issued_by))
        return EnrollmentCode(code='fme_rotated', expires_at='2026-11-01T10:10:00Z')

    def delete_server(self, server_id):
        self._check()
        self.calls.append(('delete', str(server_id)))
        self.store.pop(str(server_id), None)

    def servers(self):
        self._check()
        return self.legacy

    def link(self, server_id, organization_id, owner_id):
        self.calls.append(('link', str(server_id), str(organization_id), str(owner_id)))

    def statuses(self):
        self._check()
        return {sid: ServerStatus(online=True, last_report_at='2026-11-01T10:00:00Z') for sid in self.store}


@pytest.fixture
def mobile(monkeypatch):
    fake = FakeMobile()
    monkeypatch.setattr(forail_mobile, 'ForailMobileClient', fake)
    with override_settings(
        FORAIL_MOBILE_URL='http://mobile.test',
        FORAIL_MOBILE_PUBLIC_URL='https://mobile.example.com',
        FORAIL_MOBILE_SERVICE_TOKEN=SERVICE_TOKEN,
    ):
        yield fake


@pytest.fixture
def org1():
    return Organization.objects.create(name='org-1')


@pytest.fixture
def org2():
    return Organization.objects.create(name='org-2')


def _member(name, org):
    u = User.objects.create(username=name)
    org.member_role.members.add(u)
    return u


@pytest.fixture
def a(org1):
    return _member('user-a', org1)


@pytest.fixture
def b(org1):
    return _member('user-b', org1)


@pytest.fixture
def c(org2):
    return _member('user-c', org2)


@pytest.fixture
def d(org1):
    u = _member('admin-d', org1)
    org1.admin_role.members.add(u)
    return u


@pytest.fixture
def server(post, mobile, org1, a):
    r = post('/api/v2/monitored_servers/', {'name': 'web-01', 'organization': org1.pk}, a, expect=201)
    return MonitoredServer.objects.get(pk=r.data['id'])


def _url(server, suffix=''):
    return f'/api/v2/monitored_servers/{server.pk}/{suffix}'


# --- create -----------------------------------------------------------------------


def test_member_registers_a_server_and_owns_it(post, mobile, org1, a):
    r = post('/api/v2/monitored_servers/', {'name': 'web-01', 'organization': org1.pk}, a, expect=201)
    server = MonitoredServer.objects.get(pk=r.data['id'])
    assert server.owner == a
    assert a in server.admin_role
    assert mobile.calls == [('create', 'web-01', str(org1.pk), str(a.pk))]
    assert str(server.mobile_server_id) in mobile.store
    assert r.data['owner'] == a.pk


def test_cannot_register_in_an_organization_you_are_not_in(post, mobile, org2, a):
    post('/api/v2/monitored_servers/', {'name': 'web-01', 'organization': org2.pk}, a, expect=403)
    assert mobile.calls == []


def test_duplicate_name_refused_within_an_organization_allowed_across(post, mobile, org1, org2, a, b, c):
    post('/api/v2/monitored_servers/', {'name': 'web-01', 'organization': org1.pk}, a, expect=201)
    post('/api/v2/monitored_servers/', {'name': 'web-01', 'organization': org1.pk}, b, expect=400)
    post('/api/v2/monitored_servers/', {'name': 'web-01', 'organization': org2.pk}, c, expect=201)


def test_invalid_name_refused(post, mobile, org1, a):
    post('/api/v2/monitored_servers/', {'name': 'web 01; rm -rf', 'organization': org1.pk}, a, expect=400)
    assert mobile.calls == []


@override_settings(MONITORED_SERVERS_PER_USER=2)
def test_quota_per_user(post, mobile, org1, a, admin):
    for n in range(2):
        post('/api/v2/monitored_servers/', {'name': f'web-{n}', 'organization': org1.pk}, a, expect=201)
    r = post('/api/v2/monitored_servers/', {'name': 'web-9', 'organization': org1.pk}, a, expect=409)
    assert 'most one user' in str(r.data)
    # Superusers are not limited.
    for n in range(3):
        post('/api/v2/monitored_servers/', {'name': f'su-{n}', 'organization': org1.pk}, admin, expect=201)


def test_mobile_down_on_create_is_503_and_nothing_saved(post, mobile, org1, a):
    mobile.unavailable = True
    post('/api/v2/monitored_servers/', {'name': 'web-01', 'organization': org1.pk}, a, expect=503)
    assert MonitoredServer.objects.count() == 0


def test_feature_off_without_configuration(post, org1, a):
    with override_settings(FORAIL_MOBILE_URL='', FORAIL_MOBILE_SERVICE_TOKEN=''):
        post('/api/v2/monitored_servers/', {'name': 'web-01', 'organization': org1.pk}, a, expect=503)


def test_conflict_in_mobile_is_409(post, mobile, org1, a):
    mobile.conflict = True
    post('/api/v2/monitored_servers/', {'name': 'web-01', 'organization': org1.pk}, a, expect=409)
    assert MonitoredServer.objects.count() == 0


# --- who sees it ------------------------------------------------------------------


def test_visibility(get, server, a, b, c, d, admin):
    for viewer in (a, d, admin):
        assert [s['id'] for s in get('/api/v2/monitored_servers/', viewer, expect=200).data['results']] == [server.pk]
        get(_url(server), viewer, expect=200)
    for outsider in (b, c):
        assert get('/api/v2/monitored_servers/', outsider, expect=200).data['count'] == 0
        get(_url(server), outsider, expect=404)
        get(_url(server, 'access_list/'), outsider, expect=404)
        get(_url(server, 'object_roles/'), outsider, expect=404)
        get(_url(server, 'activity_stream/'), outsider, expect=404)


def test_online_comes_from_mobile(get, server, a, mobile):
    data = get(_url(server), a, expect=200).data
    assert data['online'] is True and data['last_report_at'] == '2026-11-01T10:00:00Z'
    mobile.unavailable = True
    data = get(_url(server), a, expect=200).data
    assert data['online'] is None


def test_capabilities(get, server, a, d, admin):
    owner = get(_url(server), a, expect=200).data['summary_fields']['user_capabilities']
    assert owner == {'edit': True, 'delete': True, 'rotate': True, 'manage_access': False}
    for manager in (d, admin):
        caps = get(_url(server), manager, expect=200).data['summary_fields']['user_capabilities']
        assert caps['manage_access'] is True and caps['rotate'] is True


def test_granted_reader_sees_but_cannot_manage(get, post, delete, server, b):
    server.read_role.members.add(b)
    get(_url(server), b, expect=200)
    caps = get(_url(server), b, expect=200).data['summary_fields']['user_capabilities']
    assert caps == {'edit': False, 'delete': False, 'rotate': False, 'manage_access': False}
    post(_url(server, 'rotate_token/'), {}, b, expect=403)
    post(_url(server, 'enrollment_code/'), {}, b, expect=403)
    delete(_url(server), b, expect=403)


# --- grant and revoke --------------------------------------------------------------


def test_org_admin_grants_and_revokes(get, post, server, b, d):
    role = server.read_role
    post(f'/api/v2/users/{b.pk}/roles/', {'id': role.pk}, d, expect=204)
    get(_url(server), b, expect=200)
    post(f'/api/v2/users/{b.pk}/roles/', {'id': role.pk, 'disassociate': True}, d, expect=204)
    get(_url(server), b, expect=404)


def test_owner_cannot_share_their_server(post, server, a, b):
    post(f'/api/v2/users/{b.pk}/roles/', {'id': server.read_role.pk}, a, expect=403)
    post(f'/api/v2/users/{b.pk}/roles/', {'id': server.admin_role.pk}, a, expect=403)
    assert b not in server.read_role


@pytest.mark.usefixtures('setup_managed_roles')
def test_owner_cannot_share_through_role_assignments(server, a, b):
    """The same rule holds for django-ansible-base assignments, whatever API makes them."""
    rd = RoleDefinition.objects.get(name='MonitoredServer Admin')
    with impersonate(a), pytest.raises(PermissionDenied):
        rd.give_permission(b, server)
    assert b not in server.read_role


@pytest.mark.usefixtures('setup_managed_roles')
def test_org_admin_can_assign_through_role_assignments(server, b, d):
    rd = RoleDefinition.objects.get(name='MonitoredServer Admin')
    with impersonate(d):
        rd.give_permission(b, server)
    assert MonitoredServerAccess(b).can_read(server)


def test_org_admin_of_another_org_cannot_grant(post, server, b, org2):
    other_admin = _member('admin-e', org2)
    org2.admin_role.members.add(other_admin)
    post(f'/api/v2/users/{b.pk}/roles/', {'id': server.read_role.pk}, other_admin, expect=403)


# --- enrollment, rotation, delete ---------------------------------------------------


def test_enrollment_code_and_install_command(post, server, a, mobile):
    r = post(_url(server, 'enrollment_code/'), {}, a, expect=201)
    assert r.data['code'] == 'fme_onetime'
    assert r.data['api_url'] == 'https://mobile.example.com'
    assert r.data['command'] == 'sudo forail-agent enroll --api https://mobile.example.com --code fme_onetime'
    assert ('enrollment_code', str(server.mobile_server_id), a.pk) in mobile.calls
    assert 'fma_' not in str(r.data)  # never a long-lived agent token


def test_rotate_returns_a_code_not_a_token(post, server, d, mobile):
    r = post(_url(server, 'rotate_token/'), {}, d, expect=201)
    assert r.data['code'] == 'fme_rotated'
    assert ('rotate', str(server.mobile_server_id), d.pk) in mobile.calls


def test_enrollment_on_invisible_server_is_404(post, server, c):
    post(_url(server, 'enrollment_code/'), {}, c, expect=404)
    post(_url(server, 'rotate_token/'), {}, c, expect=404)


def test_owner_deletes(delete, server, a, mobile):
    delete(_url(server), a, expect=204)
    assert not MonitoredServer.objects.filter(pk=server.pk).exists()
    assert ('delete', str(server.mobile_server_id)) in mobile.calls


def test_delete_refused_while_mobile_is_down(delete, server, a, mobile):
    mobile.unavailable = True
    delete(_url(server), a, expect=503)
    assert MonitoredServer.objects.filter(pk=server.pk).exists()


def test_name_and_organization_are_fixed(patch, server, a, org2):
    patch(_url(server), {'name': 'renamed'}, a, expect=400)
    patch(_url(server), {'organization': org2.pk}, a, expect=403)
    patch(_url(server), {'description': 'front end'}, a, expect=200)


def test_activity_stream(post, server, a, d):
    post(_url(server, 'enrollment_code/'), {}, a, expect=201)
    post(_url(server, 'rotate_token/'), {}, d, expect=201)
    entries = ActivityStream.objects.filter(monitored_server=server)
    operations = sorted(e.operation for e in entries)
    assert 'create' in operations
    changes = ' '.join(e.changes for e in entries)
    assert 'enrollment_code' in changes and 'agent_token' in changes


# --- service API for the Forail Mobile backend ----------------------------------------


def _service(get, path, token=SERVICE_TOKEN, user=None):
    headers = {'HTTP_AUTHORIZATION': f'Service {token}'} if token else {}
    return get(path, user, **headers)


def test_service_visible(get, server, a, b, c, d, admin):
    for viewer, role in ((a, 'admin'), (d, 'admin'), (admin, 'admin')):
        r = _service(get, f'/api/v2/monitored_servers/service/visible/?user={viewer.pk}')
        assert r.status_code == 200
        assert r.data['results'] == [{'mobile_server_id': str(server.mobile_server_id), 'role': role}]
    for outsider in (b, c):
        assert _service(get, f'/api/v2/monitored_servers/service/visible/?user={outsider.pk}').data['results'] == []
    server.read_role.members.add(b)
    assert _service(get, f'/api/v2/monitored_servers/service/visible/?user={b.pk}').data['results'][0]['role'] == 'read'


def test_service_refuses_users_and_wrong_tokens(get, server, a, admin):
    assert _service(get, f'/api/v2/monitored_servers/service/visible/?user={a.pk}', token=None, user=admin).status_code == 403
    assert _service(get, f'/api/v2/monitored_servers/service/visible/?user={a.pk}', token='wrong').status_code == 403
    with override_settings(FORAIL_MOBILE_SERVICE_TOKEN=''):
        assert _service(get, f'/api/v2/monitored_servers/service/visible/?user={a.pk}', token='').status_code == 404


def test_service_unknown_user_is_404(get, mobile):
    assert _service(get, '/api/v2/monitored_servers/service/visible/?user=999999').status_code == 404


def test_service_access_list(get, server, a, b, d, admin):
    server.read_role.members.add(b)
    r = _service(get, f'/api/v2/monitored_servers/service/access/?server={server.mobile_server_id}')
    assert r.status_code == 200
    by_user = {e['username']: (e['role'], e['source']) for e in r.data['results']}
    assert by_user[a.username] == ('admin', 'owner')
    assert by_user[d.username] == ('admin', 'org_admin')
    assert by_user[admin.username] == ('admin', 'superuser')
    assert by_user[b.username] == ('read', 'granted')
    assert 'user-c' not in by_user


def test_service_access_unknown_server_is_404(get, mobile):
    assert _service(get, f'/api/v2/monitored_servers/service/access/?server={uuid.uuid4()}').status_code == 404


def test_grant_and_revoke_reach_the_activity_stream(server, b, d):
    with impersonate(d):
        server.read_role.members.add(b)
        server.read_role.members.remove(b)
    operations = list(ActivityStream.objects.filter(role__in=[server.read_role]).values_list('operation', flat=True))
    assert 'associate' in operations and 'disassociate' in operations


# --- import of servers registered before #52 -------------------------------------------


def test_import_monitored_servers(mobile, org1, a, b, server):
    from django.core.management import call_command

    mobile.legacy = [
        {'id': str(server.mobile_server_id), 'name': 'web-01', 'legacy_members': []},  # already linked
        {'id': str(uuid.uuid4()), 'name': 'db-01', 'legacy_members': [str(b.pk)]},
        {'id': str(uuid.uuid4()), 'name': 'bad name', 'legacy_members': []},
        {'id': str(uuid.uuid4()), 'name': 'cache-01', 'legacy_members': []},
    ]
    call_command('import_monitored_servers', organization=org1.name, owner=a.username, grant_members=True, only='db-01,bad name,web-01', dry_run=True)
    assert MonitoredServer.objects.count() == 1

    call_command('import_monitored_servers', organization=org1.name, owner=a.username, grant_members=True, only='db-01,bad name,web-01')
    db = MonitoredServer.objects.get(name='db-01')
    assert db.owner == a and a in db.admin_role
    assert MonitoredServerAccess(b).can_read(db)
    assert ('link', mobile.legacy[1]['id'], str(org1.pk), str(a.pk)) in mobile.calls
    assert not MonitoredServer.objects.filter(name='cache-01').exists()

    call_command('import_monitored_servers', organization=org1.name, owner=a.username)  # re-run: only cache-01 is new
    assert MonitoredServer.objects.filter(name='cache-01').exists()
    assert MonitoredServer.objects.count() == 3
