"""Outbound webhooks fire on job and workflow status changes, per organization.

dispatch_outbound_webhooks existed but nothing called it: a configured
webhook only ever received the test payload. It also selected matching
webhooks from every organization, so once wired, each tenant would have
received every other tenant's job events.
"""

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

    job = Job.objects.create(name='deploy', organization=organization, status='successful')
    _notify(job, 'succeeded', django_capture_on_commit_callbacks)

    assert sorted(pk for pk, _ in sent) == sorted([mine.pk, global_hook.pk])
    payload = sent[0][1]
    assert payload['event_type'] == 'job.succeeded'
    assert payload['job']['id'] == job.id


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
