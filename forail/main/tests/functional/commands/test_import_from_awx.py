"""End-to-end tests for the ``import_from_awx`` management command.

The source AWX REST API is replaced with an in-memory fake (``FakeAWXClient``)
that returns canned, AWX-shaped payloads, so the test exercises the real Forail
ORM writes end to end without any network access. Coverage spans every resource
type the importer handles, the secret-stripping behaviour, the workflow node DAG,
notification wiring and — the headline follow-up — RBAC role assignments
(user grant, team grant, and singleton system roles).

DB-backed; runs under the canonical ``make docker-compose-runtest`` target
(Postgres + full migrations).
"""

import pytest

from django.contrib.auth.models import User
from django.core.management import call_command

from forail.main.models.organization import Organization, Team
from forail.main.models.credential import Credential, CredentialType
from forail.main.models.projects import Project
from forail.main.models.inventory import Inventory, Host, Group, InventorySource
from forail.main.models.jobs import JobTemplate
from forail.main.models.workflow import WorkflowJobTemplate, WorkflowJobTemplateNode
from forail.main.models.notifications import NotificationTemplate
from forail.main.models.schedules import Schedule


# --- canned AWX dataset ----------------------------------------------------

AWX_DATA = {
    'organizations': [
        {'id': 1, 'name': 'Acme', 'description': 'Acme org', 'max_hosts': 50},
    ],
    'users': [
        {'id': 10, 'username': 'alice', 'first_name': 'Alice', 'last_name': 'A',
         'email': 'alice@example.com', 'is_superuser': False},
        {'id': 11, 'username': 'bob', 'first_name': 'Bob', 'last_name': 'B',
         'email': 'bob@example.com', 'is_superuser': False},
        {'id': 12, 'username': 'root', 'first_name': '', 'last_name': '',
         'email': '', 'is_superuser': True},
    ],
    'teams': [
        {'id': 20, 'name': 'Ops', 'description': '', 'organization': 1},
    ],
    'credential_types': [
        {'id': 30, 'name': 'My Cloud', 'kind': 'cloud', 'managed': False,
         'inputs': {'fields': []}, 'injectors': {}},
    ],
    'credentials': [
        {'id': 40, 'name': 'cloud-cred', 'credential_type': 30, 'organization': 1,
         'inputs': {'username': 'svc', 'password': '$encrypted$'}},
    ],
    'projects': [
        {'id': 50, 'name': 'proj', 'organization': 1, 'scm_type': 'git',
         'scm_url': 'https://example.com/repo.git', 'credential': 40},
    ],
    'inventories': [
        {'id': 60, 'name': 'inv', 'organization': 1, 'variables': {'k': 'v'}, 'kind': ''},
    ],
    'groups': [
        {'id': 70, 'name': 'parent', 'inventory': 60, 'variables': ''},
        {'id': 71, 'name': 'child', 'inventory': 60, 'variables': ''},
    ],
    'hosts': [
        {'id': 80, 'name': 'host1', 'inventory': 60, 'enabled': True, 'variables': ''},
    ],
    'inventory_sources': [
        {'id': 90, 'name': 'src', 'inventory': 60, 'source': 'scm',
         'source_project': 50, 'source_path': 'inv.ini', 'overwrite': True,
         'update_on_launch': True, 'update_cache_timeout': 60, 'verbosity': 1},
    ],
    'job_templates': [
        {'id': 100, 'name': 'jt', 'inventory': 60, 'project': 50,
         'playbook': 'site.yml', 'job_type': 'run', 'extra_vars': {'x': 1}},
    ],
    'workflow_job_templates': [
        {'id': 110, 'name': 'wf', 'organization': 1, 'extra_vars': '',
         'allow_simultaneous': False, 'survey_enabled': False},
    ],
    'workflow_job_template_nodes': [
        {'id': 120, 'workflow_job_template': 110, 'unified_job_template': 100,
         'identifier': 'node-a', 'all_parents_must_converge': False},
        {'id': 121, 'workflow_job_template': 110, 'unified_job_template': 110,
         'identifier': 'node-b', 'all_parents_must_converge': True},
    ],
    'notification_templates': [
        {'id': 130, 'name': 'slack', 'organization': 1, 'notification_type': 'slack',
         'notification_configuration': {'channels': ['#ops'], 'token': '$encrypted$'},
         'messages': None},
    ],
    'schedules': [
        {'id': 140, 'name': 'nightly', 'unified_job_template': 100,
         'rrule': 'DTSTART:20300101T000000Z RRULE:FREQ=DAILY;INTERVAL=1',
         'enabled': True},
    ],
    'roles': [
        # User alice is Admin of the org.
        {'id': 200, 'role_field': 'admin_role',
         'summary_fields': {'resource_type': 'organization', 'resource_id': 1}},
        # Team Ops has Execute on the job template.
        {'id': 201, 'role_field': 'execute_role',
         'summary_fields': {'resource_type': 'job_template', 'resource_id': 100}},
        # Singleton system auditor for bob (no resource).
        {'id': 202, 'role_field': 'system_auditor', 'summary_fields': {}},
    ],
}

SUB_DATA = {
    # (resource, obj_id, sub) -> list
    ('groups', 70, 'children'): [{'id': 71}],
    ('hosts', 80, 'groups'): [{'id': 70}],
    ('inventory_sources', 90, 'credentials'): [{'id': 40}],
    ('job_templates', 100, 'credentials'): [{'id': 40}],
    ('job_templates', 100, 'notification_templates_started'): [{'id': 130}],
    ('workflow_job_template_nodes', 120, 'success_nodes'): [{'id': 121}],
    ('roles', 200, 'users'): [{'id': 10}],
    ('roles', 201, 'teams'): [{'id': 20}],
    ('roles', 202, 'users'): [{'id': 11}],
}


class FakeSession:
    headers = {}

    def get(self, url, **kwargs):
        class _Resp:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {'results': [], 'next': None}

        return _Resp()


class FakeAWXClient:
    def __init__(self, *args, **kwargs):
        self.base_url = 'https://awx.example.com'
        self.verify = True
        self.timeout = 30
        self.session = FakeSession()

    def get_list(self, resource):
        yield from AWX_DATA.get(resource.strip('/'), [])

    def get_sub_list(self, resource, obj_id, sub):
        yield from SUB_DATA.get((resource.strip('/'), obj_id, sub), [])


@pytest.fixture
def fake_awx(mocker):
    mocker.patch(
        'forail.main.management.commands.import_from_awx.AWXClient',
        FakeAWXClient,
    )


@pytest.mark.django_db
def test_import_creates_all_resources(fake_awx):
    call_command('import_from_awx', url='https://awx.example.com', token='t')

    org = Organization.objects.get(name='Acme')
    assert org.max_hosts == 50
    assert Team.objects.filter(name='Ops', organization=org).exists()

    alice = User.objects.get(username='alice')
    assert not alice.has_usable_password()  # passwords are never exported

    ct = CredentialType.objects.get(name='My Cloud')
    cred = Credential.objects.get(name='cloud-cred', credential_type=ct)
    # The $encrypted$ password must be stripped, the plain username kept.
    assert cred.inputs == {'username': 'svc'}

    proj = Project.objects.get(name='proj', organization=org)
    assert proj.credential == cred

    inv = Inventory.objects.get(name='inv', organization=org)
    parent = Group.objects.get(name='parent', inventory=inv)
    child = Group.objects.get(name='child', inventory=inv)
    assert child in parent.children.all()
    host = Host.objects.get(name='host1', inventory=inv)
    assert host in parent.hosts.all()

    src = InventorySource.objects.get(name='src', inventory=inv)
    assert src.source == 'scm'
    assert src.source_project == proj
    assert src.update_on_launch is True
    assert cred in src.credentials.all()

    jt = JobTemplate.objects.get(name='jt')
    assert jt.project == proj and jt.inventory == inv
    assert cred in jt.credentials.all()


@pytest.mark.django_db
def test_import_workflow_graph(fake_awx):
    call_command('import_from_awx', url='https://awx.example.com', token='t')

    wf = WorkflowJobTemplate.objects.get(name='wf')
    node_a = WorkflowJobTemplateNode.objects.get(workflow_job_template=wf, identifier='node-a')
    node_b = WorkflowJobTemplateNode.objects.get(workflow_job_template=wf, identifier='node-b')
    # node-a points at the job template, node-b nests the workflow itself.
    assert node_a.unified_job_template_id == JobTemplate.objects.get(name='jt').id
    assert node_b.unified_job_template_id == wf.id
    assert node_b.all_parents_must_converge is True
    # The DAG edge node-a --success--> node-b was wired in the second pass.
    assert node_b in node_a.success_nodes.all()


@pytest.mark.django_db
def test_import_notifications_and_schedule(fake_awx):
    call_command('import_from_awx', url='https://awx.example.com', token='t')

    org = Organization.objects.get(name='Acme')
    nt = NotificationTemplate.objects.get(name='slack', organization=org)
    # Secret token blanked (needs re-entry); non-secret config retained.
    assert nt.notification_configuration == {'channels': ['#ops'], 'token': ''}
    jt = JobTemplate.objects.get(name='jt')
    assert nt in jt.notification_templates_started.all()

    sched = Schedule.objects.get(name='nightly')
    assert sched.unified_job_template_id == jt.id
    assert sched.enabled is True


@pytest.mark.django_db
def test_import_rbac_role_assignments(fake_awx):
    call_command('import_from_awx', url='https://awx.example.com', token='t')

    org = Organization.objects.get(name='Acme')
    alice = User.objects.get(username='alice')
    bob = User.objects.get(username='bob')
    team = Team.objects.get(name='Ops', organization=org)
    jt = JobTemplate.objects.get(name='jt')

    # Direct user grant: alice is an org admin.
    assert alice in org.admin_role.members.all()
    # Team grant: the JT execute_role inherits from the team's member_role.
    assert team.member_role in jt.execute_role.parents.all()
    # Singleton: bob became a system auditor.
    bob.refresh_from_db()
    assert bob.is_system_auditor


@pytest.mark.django_db
def test_dry_run_writes_nothing(fake_awx):
    call_command('import_from_awx', url='https://awx.example.com', token='t', dry_run=True)
    assert not Organization.objects.filter(name='Acme').exists()
    assert not JobTemplate.objects.filter(name='jt').exists()
    assert not Schedule.objects.filter(name='nightly').exists()


@pytest.mark.django_db
def test_resource_filter_limits_scope(fake_awx):
    call_command('import_from_awx', url='https://awx.example.com', token='t',
                 resource=['organizations'])
    assert Organization.objects.filter(name='Acme').exists()
    # Nothing downstream of organizations should have been imported.
    assert not JobTemplate.objects.filter(name='jt').exists()
    assert not Inventory.objects.filter(name='inv').exists()


@pytest.mark.django_db
def test_import_is_idempotent(fake_awx):
    call_command('import_from_awx', url='https://awx.example.com', token='t')
    call_command('import_from_awx', url='https://awx.example.com', token='t')
    # Re-running matches by natural key rather than duplicating.
    assert Organization.objects.filter(name='Acme').count() == 1
    assert JobTemplate.objects.filter(name='jt').count() == 1
    assert WorkflowJobTemplateNode.objects.filter(identifier='node-a').count() == 1
    assert Schedule.objects.filter(name='nightly').count() == 1
