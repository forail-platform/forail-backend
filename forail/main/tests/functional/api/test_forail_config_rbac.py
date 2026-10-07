"""Who may read and change Forail's own configuration objects.

Event rules, outbound webhooks, drift alert rules, policies, scanners and
service catalog items: anyone in the organization reads them, its admins
change them. Before 2026-10 the views checked only that the user was logged
in and in the organization, so a plain member could rewrite any of them --
disable a policy, point a webhook at their own URL, aim an event rule at a
job template in another organization. Creating one as anyone but a
superuser failed with a 500, and DELETE failed for everybody.
"""

import pytest

from django.contrib.auth.models import User
from django.test import override_settings

from forail.main.models import JobTemplate, Organization, Project
from forail.main.models.drift import DriftAlertRule
from forail.main.models.eda import EventRule, OutboundWebhook
from forail.main.models.policy import Policy
from forail.main.models.scanner import Scanner
from forail.main.models.service_catalog import ServiceCatalogItem

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures('no_opa')]


@pytest.fixture
def no_opa():
    with override_settings(OPA_SERVER_URL=''):
        yield


def _jt(org, name):
    project = Project.objects.create(name='%s-proj' % name, organization=org, scm_type='git', scm_url='localhost')
    return JobTemplate.objects.create(name=name, project=project, playbook='site.yml')


@pytest.fixture
def org_jt(organization):
    return _jt(organization, 'org-jt')


@pytest.fixture
def foreign_jt():
    return _jt(Organization.objects.create(name='elsewhere'), 'foreign-jt')


@pytest.fixture
def outsider():
    org = Organization.objects.create(name='other-org')
    u = User.objects.create(username='outsider')
    org.member_role.members.add(u)
    return u


# endpoint, model, payload builder (organization, job template) -> dict
CONFIG = [
    ('event_rules', EventRule, lambda org, jt: {
        'name': 'rule', 'organization': org.id, 'webhook_path': 'rule-path', 'source_type': 'webhook_generic',
        'actions': [{'action_type': 'launch_job_template', 'target_id': jt.id}],
    }),
    ('outbound_webhooks', OutboundWebhook, lambda org, jt: {
        'name': 'hook', 'organization': org.id, 'target_url': 'https://hooks.example/f', 'events': ['job.failed'],
    }),
    ('drift_alert_rules', DriftAlertRule, lambda org, jt: {'name': 'drift', 'organization': org.id}),
    ('policies', Policy, lambda org, jt: {'name': 'policy', 'organization': org.id, 'rego_module': 'package forail.x'}),
    ('scanners', Scanner, lambda org, jt: {'name': 'scanner', 'organization': org.id}),
    ('service_catalog_items', ServiceCatalogItem, lambda org, jt: {'name': 'item', 'organization': org.id, 'job_template': jt.id}),
]
IDS = [c[0] for c in CONFIG]


def _create(post, endpoint, payload, user, expect):
    r = post('/api/v2/%s/' % endpoint, payload, user, expect=expect)
    return r.data.get('id') if expect == 201 else None


@pytest.mark.parametrize('endpoint,model,payload', CONFIG, ids=IDS)
def test_org_admin_manages_the_full_lifecycle(endpoint, model, payload, post, patch, delete, organization, org_admin, org_jt):
    pk = _create(post, endpoint, payload(organization, org_jt), org_admin, 201)
    patch('/api/v2/%s/%s/' % (endpoint, pk), {'description': 'edited'}, org_admin, expect=200)
    delete('/api/v2/%s/%s/' % (endpoint, pk), user=org_admin, expect=204)
    assert not model.objects.filter(pk=pk).exists()


@pytest.mark.parametrize('endpoint,model,payload', CONFIG, ids=IDS)
def test_member_and_auditor_read_but_cannot_change(endpoint, model, payload, post, get, patch, delete, organization, admin, org_member, org_auditor, org_jt):
    pk = _create(post, endpoint, payload(organization, org_jt), admin, 201)
    url = '/api/v2/%s/%s/' % (endpoint, pk)
    for user in (org_member, org_auditor):
        get(url, user=user, expect=200)
        patch(url, {'description': 'nope'}, user, expect=403)
        delete(url, user=user, expect=403)
        post('/api/v2/%s/' % endpoint, dict(payload(organization, org_jt), name='mine', webhook_path='mine'), user, expect=403)
    assert model.objects.get(pk=pk).description == ''


@pytest.mark.parametrize('endpoint,model,payload', CONFIG, ids=IDS)
def test_other_organizations_see_nothing(endpoint, model, payload, post, get, patch, organization, admin, outsider, org_jt):
    pk = _create(post, endpoint, payload(organization, org_jt), admin, 201)
    url = '/api/v2/%s/%s/' % (endpoint, pk)
    # 403, not 404, as everywhere else in the AWX API.
    get(url, user=outsider, expect=403)
    patch(url, {'description': 'nope'}, outsider, expect=403)
    listed = get('/api/v2/%s/' % endpoint, user=outsider, expect=200).data['results']
    assert pk not in [o['id'] for o in listed]


@pytest.mark.parametrize('endpoint', ['event_rules', 'drift_alert_rules', 'policies', 'scanners'])
def test_only_admins_toggle(endpoint, post, organization, admin, org_admin, org_member, org_jt):
    payload = [c for c in CONFIG if c[0] == endpoint][0][2]
    pk = _create(post, endpoint, payload(organization, org_jt), admin, 201)
    post('/api/v2/%s/%s/disable/' % (endpoint, pk), {}, org_member, expect=403)
    post('/api/v2/%s/%s/disable/' % (endpoint, pk), {}, org_admin, expect=200)


def test_event_rule_cannot_launch_what_its_author_cannot(post, patch, organization, org_admin, org_jt, foreign_jt):
    payload = CONFIG[0][2](organization, foreign_jt)
    post('/api/v2/event_rules/', payload, org_admin, expect=403)

    pk = _create(post, 'event_rules', CONFIG[0][2](organization, org_jt), org_admin, 201)
    patch('/api/v2/event_rules/%s/' % pk, {'actions': [{'action_type': 'launch_job_template', 'target_id': foreign_jt.id}]}, org_admin, expect=403)

    foreign_jt.execute_role.members.add(org_admin)
    patch('/api/v2/event_rules/%s/' % pk, {'actions': [{'action_type': 'launch_job_template', 'target_id': foreign_jt.id}]}, org_admin, expect=200)


def test_catalog_item_needs_execute_on_its_template(post, organization, org_admin, foreign_jt):
    payload = CONFIG[5][2](organization, foreign_jt)
    post('/api/v2/service_catalog_items/', payload, org_admin, expect=403)
    foreign_jt.execute_role.members.add(org_admin)
    post('/api/v2/service_catalog_items/', payload, org_admin, expect=201)


def test_webhook_key_is_for_admins_only(post, get, organization, admin, org_admin, org_member, system_auditor, org_jt):
    pk = _create(post, 'event_rules', CONFIG[0][2](organization, org_jt), admin, 201)
    url = '/api/v2/event_rules/%s/webhook_key/' % pk
    get(url, user=org_member, expect=403)
    get(url, user=system_auditor, expect=403)
    post(url, {}, org_member, expect=403)
    assert get(url, user=org_admin, expect=200).data['webhook_key']



def test_dry_run_and_test_send_are_scoped(post, organization, admin, org_admin, outsider, org_jt, mocker):
    from forail.main.tasks import eda as eda_tasks

    send = mocker.patch.object(eda_tasks.send_outbound_webhook, 'delay')
    rule = _create(post, 'event_rules', CONFIG[0][2](organization, org_jt), admin, 201)
    hook = _create(post, 'outbound_webhooks', CONFIG[1][2](organization, org_jt), admin, 201)

    post('/api/v2/event_rules/%s/test/' % rule, {'payload': {}}, outsider, expect=403)
    post('/api/v2/outbound_webhooks/%s/test/' % hook, {}, outsider, expect=403)
    assert not send.called

    post('/api/v2/outbound_webhooks/%s/test/' % hook, {}, org_admin, expect=200)
    assert send.called
