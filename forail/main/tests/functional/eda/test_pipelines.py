"""EDA and drift, end to end, through the code paths production runs.

Both task modules used celery.shared_task. Celery is not installed in the
image -- Forail runs AWX's own dispatcher -- so importing either module
failed: the public EDA receiver raised on every event, and the drift
capture that RunJob.post_run_hook triggers after every fact-caching job
died in a logged exception. These tests drive a signed webhook into a
launched job, and two fact captures into a drift detection, with the
dispatcher's .delay replaced by a direct call.
"""

import hashlib
import hmac
import json

import pytest

from django.test import RequestFactory
from django.urls import resolve

from forail.main.dispatch.worker.task import TaskWorker
from forail.main.models import Host, Inventory, Job, JobTemplate, Project
from forail.main.models.drift import DriftDetection, HostFactSnapshot
from forail.main.models.eda import EventLog, EventRule
from forail.main.tasks import drift as drift_tasks
from forail.main.tasks import eda as eda_tasks

TASKS = [
    'forail.main.tasks.eda.evaluate_event_rule',
    'forail.main.tasks.eda.send_outbound_webhook',
    'forail.main.tasks.drift.capture_fact_snapshot',
    'forail.main.tasks.drift.detect_drift',
    'forail.main.tasks.drift.evaluate_drift_alerts',
    'forail.main.tasks.drift.cleanup_old_snapshots',
]


@pytest.mark.parametrize('name', TASKS)
def test_the_dispatcher_can_run_the_task(name):
    # What the dispatcher worker does with a message: import by dotted name
    # and insist on a @task-decorated callable.
    assert callable(TaskWorker.resolve_callable(name))


def test_cleanup_is_scheduled():
    from django.conf import settings

    tasks = {entry['task'] for entry in settings.CELERYBEAT_SCHEDULE.values()}
    assert 'forail.main.tasks.drift.cleanup_old_snapshots' in tasks


@pytest.fixture
def run_tasks_inline(mocker):
    for module, name in ((eda_tasks, 'evaluate_event_rule'), (drift_tasks, 'detect_drift'), (drift_tasks, 'evaluate_drift_alerts')):
        fn = getattr(module, name)
        mocker.patch.object(fn, 'delay', side_effect=lambda *a, _fn=fn, **kw: _fn(*a, **kw))
    mocker.patch.object(Job, 'signal_start', return_value=True)


@pytest.fixture
def launchable_jt(organization):
    project = Project.objects.create(name='p', organization=organization, scm_type='git', scm_url='localhost')
    inventory = Inventory.objects.create(name='inv', organization=organization)
    return JobTemplate.objects.create(name='restart-web', project=project, inventory=inventory, playbook='site.yml')


def _send(path, payload, key):
    body = json.dumps(payload).encode()
    signature = hmac.new(key.encode(), body, hashlib.sha256).hexdigest()
    url = '/api/v2/eda_webhooks/%s/' % path
    request = RequestFactory().post(url, data=body, content_type='application/json', HTTP_X_FORAIL_SIGNATURE='sha256=' + signature)
    match = resolve(url)
    return match.func(request, *match.args, **match.kwargs)


@pytest.mark.django_db
def test_signed_webhook_launches_the_job(organization, launchable_jt, run_tasks_inline):
    rule = EventRule.objects.create(
        name='site down',
        organization=organization,
        webhook_path='site-down',
        source_type='webhook_generic',
        webhook_key='k3y',
        conditions=[{'jinja2_expression': "event.status == 'down'"}],
        actions=[{'action_type': 'launch_job_template', 'target_id': launchable_jt.id}],
    )

    response = _send('site-down', {'status': 'down', 'site': 'shop'}, 'k3y')
    assert response.status_code in (200, 201, 202), response.content

    log = EventLog.objects.get(event_rule=rule)
    assert log.status == 'action_fired', log.error_detail
    job = Job.objects.get(pk=log.job_id)
    assert job.job_template_id == launchable_jt.id
    assert job.launch_type == 'webhook'
    assert json.loads(job.extra_vars)['forail_eda_payload'] == {'status': 'down', 'site': 'shop'}


@pytest.mark.django_db
def test_unmatched_and_unsigned_events_launch_nothing(organization, launchable_jt, run_tasks_inline):
    EventRule.objects.create(
        name='site down', organization=organization, webhook_path='site-down', source_type='webhook_generic', webhook_key='k3y',
        conditions=[{'jinja2_expression': "event.status == 'down'"}],
        actions=[{'action_type': 'launch_job_template', 'target_id': launchable_jt.id}],
    )
    _send('site-down', {'status': 'up'}, 'k3y')
    assert _send('site-down', {'status': 'down'}, 'wrong-key').status_code == 403
    assert not Job.objects.exists()
    assert set(EventLog.objects.values_list('status', flat=True)) == {'unmatched', 'signature_failed'}


@pytest.mark.django_db
def test_two_fact_captures_produce_a_drift_detection(organization, launchable_jt, run_tasks_inline):
    from django.utils.timezone import now

    host = Host.objects.create(name='web1', inventory=launchable_jt.inventory)

    def capture(facts):
        Host.objects.filter(pk=host.pk).update(ansible_facts=facts, ansible_facts_modified=now())
        job = Job.objects.create(job_template=launchable_jt, inventory=launchable_jt.inventory)
        drift_tasks.capture_fact_snapshot(job.id)

    capture({'ansible_distribution_version': '22.04', 'ansible_kernel': '5.15.0-91'})
    assert HostFactSnapshot.objects.filter(host=host).count() == 1
    assert not DriftDetection.objects.exists()  # the first snapshot is the baseline

    capture({'ansible_distribution_version': '22.04', 'ansible_kernel': '5.15.0-105'})
    assert HostFactSnapshot.objects.filter(host=host).count() == 2
    detection = DriftDetection.objects.get(host=host)
    assert 'ansible_kernel' in detection.fact_path

    # Unchanged facts are not a new snapshot.
    capture({'ansible_distribution_version': '22.04', 'ansible_kernel': '5.15.0-105'})
    assert HostFactSnapshot.objects.filter(host=host).count() == 2
