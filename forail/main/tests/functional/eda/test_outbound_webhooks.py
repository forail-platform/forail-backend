"""Outbound webhooks fire on job and workflow status changes, per organization.

dispatch_outbound_webhooks existed but nothing called it: a configured
webhook only ever received the test payload. It also selected matching
webhooks from every organization, so once wired, each tenant would have
received every other tenant's job events.
"""

import json
from decimal import Decimal

import pytest

from forail.main.models import Job, Organization, WorkflowJob
from forail.main.models.eda import OutboundWebhook
from forail.main.tasks import eda as eda_tasks


@pytest.fixture
def sent(mocker):
    calls = []
    mocker.patch.object(eda_tasks.send_outbound_webhook, 'delay', side_effect=lambda pk, data: calls.append((pk, data)))
    return calls


def _hook(org, name, events):
    return OutboundWebhook.objects.create(name=name, organization=org, url='https://hooks.example/%s' % name, events=events)


def _notify(job, status, capture):
    with capture(execute=True):
        job.send_notification_templates(status)


@pytest.mark.django_db
def test_job_events_reach_only_their_organization(organization, sent, django_capture_on_commit_callbacks):
    other = Organization.objects.create(name='other')
    mine = _hook(organization, 'mine', ['job.succeeded', 'job.failed'])
    _hook(other, 'theirs', ['job.succeeded'])
    _hook(organization, 'only-failures', ['job.failed'])
    global_hook = _hook(None, 'global', ['job.succeeded'])

    job = Job.objects.create(name='deploy', organization=organization, status='successful', elapsed=Decimal('12.345'))
    _notify(job, 'succeeded', django_capture_on_commit_callbacks)

    assert sorted(pk for pk, _ in sent) == sorted([mine.pk, global_hook.pk])
    payload = sent[0][1]
    # What the dispatcher does with task arguments: plain json.dumps, no default=.
    json.dumps(payload)
    assert payload['event_type'] == 'job.succeeded'
    assert payload['job']['id'] == job.id
    assert payload['job']['name'] == 'deploy'


@pytest.mark.django_db
@pytest.mark.parametrize(
    'model,job_status,notify_status,event',
    [
        (Job, 'running', 'running', 'job.started'),
        (Job, 'failed', 'failed', 'job.failed'),
        (Job, 'canceled', 'failed', 'job.canceled'),
        (WorkflowJob, 'successful', 'succeeded', 'workflow.succeeded'),
        (WorkflowJob, 'failed', 'failed', 'workflow.failed'),
    ],
)
def test_status_maps_to_event(model, job_status, notify_status, event, organization, sent, django_capture_on_commit_callbacks):
    hook = _hook(organization, 'all', [e for e, _ in OutboundWebhook.EVENT_CHOICES])
    job = model.objects.create(name='x', organization=organization, status=job_status)
    _notify(job, notify_status, django_capture_on_commit_callbacks)
    assert [(pk, data['event_type']) for pk, data in sent] == [(hook.pk, event)]


@pytest.mark.django_db
def test_disabled_webhooks_are_skipped(organization, sent, django_capture_on_commit_callbacks):
    hook = _hook(organization, 'off', ['job.succeeded'])
    hook.enabled = False
    hook.save()
    _notify(Job.objects.create(name='x', organization=organization, status='successful'), 'succeeded', django_capture_on_commit_callbacks)
    assert sent == []


@pytest.mark.django_db
def test_a_webhook_failure_never_breaks_notifications(organization, mocker, django_capture_on_commit_callbacks):
    mocker.patch.object(eda_tasks, 'dispatch_outbound_webhooks', side_effect=RuntimeError('boom'))
    job = Job.objects.create(name='x', organization=organization, status='successful')
    _notify(job, 'succeeded', django_capture_on_commit_callbacks)  # must not raise


@pytest.mark.django_db
def test_send_posts_a_signed_payload_and_records_the_result(organization, mocker):
    import hashlib
    import hmac

    hook = OutboundWebhook.objects.create(
        name='signed', organization=organization, url='https://hooks.example/x', webhook_key='k3y',
        custom_headers={'X-Team': 'ops'}, events=['job.failed'],
    )
    post = mocker.patch('requests.post')
    post.return_value.status_code = 200
    data = {'event_type': 'job.failed', 'job': {'id': 7}}

    eda_tasks.send_outbound_webhook(hook.pk, data)

    (url,), kwargs = post.call_args
    assert url == 'https://hooks.example/x'
    body = kwargs['data']
    assert json.loads(body) == data
    expected = hmac.new(b'k3y', body, hashlib.sha256).hexdigest()
    assert kwargs['headers']['X-Forail-Signature'] == 'sha256=' + expected
    assert kwargs['headers']['X-Team'] == 'ops'
    hook.refresh_from_db()
    assert hook.last_status == 'success'


@pytest.mark.django_db
def test_a_failed_send_is_recorded(organization, mocker):
    import requests

    hook = OutboundWebhook.objects.create(name='down', organization=organization, url='https://hooks.example/x', events=['job.failed'])
    mocker.patch('requests.post', side_effect=requests.ConnectionError('refused'))
    eda_tasks.send_outbound_webhook(hook.pk, {'event_type': 'job.failed'})
    hook.refresh_from_db()
    assert hook.last_status == 'failed'
    assert 'refused' in hook.last_error
