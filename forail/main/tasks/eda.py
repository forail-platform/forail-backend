"""
EDA (Event-Driven Automation) Celery tasks.

Core rule evaluation engine: receives webhook events, evaluates Jinja2 conditions,
and dispatches actions (launch jobs, workflows, notifications).
"""

import json
import logging

import hmac as hmac_mod
from hashlib import sha256

from celery import shared_task
from django.utils.encoding import force_bytes
from django.utils.timezone import now
from jinja2 import sandbox, ChainableUndefined

logger = logging.getLogger('forail.main.tasks.eda')


@shared_task(name='forail.main.tasks.eda.evaluate_event_rule')
def evaluate_event_rule(event_log_id):
    """
    Evaluate an EventRule's conditions against a received webhook payload.
    If all conditions match, execute the configured actions.
    """
    from forail.main.models.eda import EventLog

    try:
        event_log = EventLog.objects.select_related('event_rule', 'event_rule__organization').get(pk=event_log_id)
    except EventLog.DoesNotExist:
        logger.error("EventLog %s not found", event_log_id)
        return

    rule = event_log.event_rule
    if not rule:
        event_log.status = 'error'
        event_log.error_detail = 'Event rule has been deleted'
        event_log.save(update_fields=['status', 'error_detail'])
        return

    if not rule.enabled:
        event_log.status = 'unmatched'
        event_log.error_detail = 'Rule is disabled'
        event_log.save(update_fields=['status', 'error_detail'])
        return

    # Check throttling
    if rule.is_throttled():
        event_log.status = 'throttled'
        event_log.save(update_fields=['status'])
        logger.info("EventRule %s throttled (last fired %s)", rule.pk, rule.last_fired_at)
        return

    # Evaluate conditions
    try:
        matched, condition_results = _evaluate_conditions(rule.conditions, event_log.payload, event_log.headers)
    except Exception as e:
        event_log.status = 'error'
        event_log.error_detail = f'Condition evaluation error: {e}'
        event_log.save(update_fields=['status', 'error_detail'])
        logger.exception("Error evaluating conditions for EventRule %s", rule.pk)
        return

    event_log.conditions_matched = matched
    event_log.condition_results = condition_results

    if not matched:
        event_log.status = 'unmatched'
        event_log.save(update_fields=['conditions_matched', 'condition_results', 'status'])
        logger.info("EventRule %s conditions not matched for EventLog %s", rule.pk, event_log.pk)
        return

    event_log.status = 'matched'
    event_log.save(update_fields=['conditions_matched', 'condition_results', 'status'])

    # Execute actions
    actions_triggered = []
    any_failed = False

    for i, action_config in enumerate(rule.actions):
        result = _execute_action(action_config, event_log, rule)
        actions_triggered.append(result)
        if result.get('status') == 'failed':
            any_failed = True
        if result.get('job_id'):
            event_log.job_id = result['job_id']

    event_log.actions_triggered = actions_triggered
    event_log.status = 'action_failed' if any_failed else 'action_fired'
    event_log.save(update_fields=['actions_triggered', 'status', 'job_id'])

    # Update rule firing stats
    rule.record_firing()

    # Log audit event
    _log_audit_event(rule, event_log, actions_triggered)

    logger.info(
        "EventRule %s fired %d actions for EventLog %s",
        rule.pk, len(actions_triggered), event_log.pk
    )


def _evaluate_conditions(conditions, payload, headers):
    """
    Evaluate Jinja2 conditions against the webhook payload.

    Returns (all_matched: bool, results: list of dicts).
    If conditions is empty, all_matched is True (no conditions = always match).
    """
    if not conditions:
        return True, []

    env = sandbox.ImmutableSandboxedEnvironment(undefined=ChainableUndefined)
    context = {
        'event': payload,
        'headers': headers,
    }

    results = []
    all_matched = True

    for condition in conditions:
        expr = condition.get('jinja2_expression', '')
        description = condition.get('description', '')

        try:
            template_str = f'{{% if {expr} %}}__TRUE__{{% else %}}__FALSE__{{% endif %}}'
            rendered = env.from_string(template_str).render(**context)
            matched = rendered.strip() == '__TRUE__'
        except Exception as e:
            matched = False
            results.append({
                'expression': expr,
                'description': description,
                'matched': False,
                'error': str(e),
            })
            all_matched = False
            continue

        results.append({
            'expression': expr,
            'description': description,
            'matched': matched,
        })
        if not matched:
            all_matched = False

    return all_matched, results


def _execute_action(action_config, event_log, rule):
    """Execute a single action from the rule configuration."""
    action_type = action_config.get('action_type')
    target_id = action_config.get('target_id')
    extra_vars = action_config.get('extra_vars', {})
    description = action_config.get('description', '')

    result = {
        'action_type': action_type,
        'target_id': target_id,
        'description': description,
    }

    try:
        if action_type == 'launch_job_template':
            job_id = _launch_job_template(target_id, extra_vars, event_log, rule)
            result['status'] = 'success'
            result['job_id'] = job_id

        elif action_type == 'launch_workflow':
            job_id = _launch_workflow(target_id, extra_vars, event_log, rule)
            result['status'] = 'success'
            result['job_id'] = job_id

        elif action_type == 'send_notification':
            _send_notification(target_id, event_log, rule)
            result['status'] = 'success'

        else:
            result['status'] = 'failed'
            result['error'] = f'Unknown action_type: {action_type}'

    except Exception as e:
        result['status'] = 'failed'
        result['error'] = str(e)
        logger.exception("Failed to execute action %s for EventRule %s", action_type, rule.pk)

    return result


def _launch_job_template(template_id, extra_vars, event_log, rule):
    """Launch a JobTemplate, injecting webhook event data as extra vars."""
    from forail.main.models import JobTemplate

    template = JobTemplate.objects.get(pk=template_id)

    # Merge user extra_vars with event payload
    merged_vars = dict(extra_vars or {})
    merged_vars['forail_eda_event_type'] = event_log.event_type
    merged_vars['forail_eda_event_guid'] = event_log.event_guid
    merged_vars['forail_eda_rule_name'] = rule.name
    merged_vars['forail_eda_payload'] = event_log.payload

    new_job = template.create_unified_job(
        _eager_fields={
            'launch_type': 'webhook',
            'webhook_service': rule.source_type,
            'webhook_guid': event_log.event_guid,
        },
        extra_vars=merged_vars,
    )
    new_job.signal_start()

    logger.info("Launched job %s from JobTemplate %s via EventRule %s", new_job.pk, template_id, rule.pk)
    return new_job.pk


def _launch_workflow(template_id, extra_vars, event_log, rule):
    """Launch a WorkflowJobTemplate."""
    from forail.main.models import WorkflowJobTemplate

    template = WorkflowJobTemplate.objects.get(pk=template_id)

    merged_vars = dict(extra_vars or {})
    merged_vars['forail_eda_event_type'] = event_log.event_type
    merged_vars['forail_eda_event_guid'] = event_log.event_guid
    merged_vars['forail_eda_rule_name'] = rule.name
    merged_vars['forail_eda_payload'] = event_log.payload

    new_job = template.create_unified_job(
        _eager_fields={
            'launch_type': 'webhook',
            'webhook_service': rule.source_type,
            'webhook_guid': event_log.event_guid,
        },
        extra_vars=merged_vars,
    )
    new_job.signal_start()

    logger.info("Launched workflow %s from WorkflowJobTemplate %s via EventRule %s", new_job.pk, template_id, rule.pk)
    return new_job.pk


def _send_notification(template_id, event_log, rule):
    """Send a notification using a NotificationTemplate."""
    from forail.main.models import NotificationTemplate

    nt = NotificationTemplate.objects.get(pk=template_id)

    subject = f'[Forail EDA] Rule "{rule.name}" fired'
    body = {
        'rule_name': rule.name,
        'rule_id': rule.pk,
        'source_type': rule.source_type,
        'event_type': event_log.event_type,
        'event_guid': event_log.event_guid,
        'source_ip': event_log.source_ip,
        'payload_summary': str(event_log.payload)[:500],
    }

    nt.send(subject, json.dumps(body, indent=2))
    logger.info("Sent notification via template %s for EventRule %s", template_id, rule.pk)


def _log_audit_event(rule, event_log, actions_triggered):
    """Log an AuditEvent for compliance tracking of EDA rule firings."""
    try:
        from forail.main.models.audit import AuditEvent
        AuditEvent.log(
            category='resource_change',
            action='event_rule_fired',
            severity='info',
            resource_type='event_rule',
            resource_id=rule.pk,
            resource_name=rule.name,
            description=f'Event rule "{rule.name}" fired {len(actions_triggered)} action(s)',
            detail={
                'event_log_id': event_log.pk,
                'event_type': event_log.event_type,
                'source_type': rule.source_type,
                'source_ip': event_log.source_ip,
                'actions': actions_triggered,
            },
            organization=rule.organization,
        )
    except Exception:
        logger.exception("Failed to create audit event for EventRule %s", rule.pk)


@shared_task(name='forail.main.tasks.eda.send_outbound_webhook')
def send_outbound_webhook(outbound_webhook_id, job_data):
    """
    Send an outbound webhook notification for a job status change.

    Args:
        outbound_webhook_id: ID of the OutboundWebhook configuration
        job_data: Dict with job status information to send
    """
    import httpx
    from forail.main.models.eda import OutboundWebhook

    try:
        webhook = OutboundWebhook.objects.get(pk=outbound_webhook_id)
    except OutboundWebhook.DoesNotExist:
        logger.error("OutboundWebhook %s not found", outbound_webhook_id)
        return

    if not webhook.enabled:
        return

    payload_bytes = json.dumps(job_data, default=str).encode('utf-8')

    # Sign the payload
    headers = dict(webhook.custom_headers or {})
    headers['Content-Type'] = 'application/json'
    if webhook.webhook_key:
        mac = hmac_mod.new(
            force_bytes(webhook.webhook_key),
            msg=payload_bytes,
            digestmod=sha256,
        )
        headers['X-Forail-Signature'] = f'sha256={mac.hexdigest()}'

    try:
        with httpx.Client(verify=webhook.ssl_verify, timeout=30.0) as client:
            response = client.post(webhook.url, content=payload_bytes, headers=headers)
            response.raise_for_status()

        webhook.last_status = 'success'
        webhook.last_sent_at = now()
        webhook.last_error = ''
        webhook.save(update_fields=['last_status', 'last_sent_at', 'last_error'])

        logger.info("Outbound webhook %s sent to %s (status %d)", webhook.pk, webhook.url, response.status_code)

    except Exception as e:
        webhook.last_status = 'failed'
        webhook.last_sent_at = now()
        webhook.last_error = str(e)[:1000]
        webhook.save(update_fields=['last_status', 'last_sent_at', 'last_error'])

        logger.exception("Failed to send outbound webhook %s to %s", webhook.pk, webhook.url)


def dispatch_outbound_webhooks(job, event_type):
    """
    Called when a job status changes. Dispatches outbound webhooks that match
    the event type.

    Args:
        job: UnifiedJob instance
        event_type: String like 'job.succeeded', 'job.failed', etc.
    """
    from forail.main.models.eda import OutboundWebhook

    webhooks = OutboundWebhook.objects.filter(
        enabled=True,
        events__contains=[event_type],
    )

    if not webhooks.exists():
        return

    job_data = {
        'event_type': event_type,
        'timestamp': now().isoformat(),
        'job': {
            'id': job.pk,
            'name': str(job),
            'status': job.status,
            'type': job.__class__.__name__,
            'started': str(job.started) if hasattr(job, 'started') and job.started else None,
            'finished': str(job.finished) if hasattr(job, 'finished') and job.finished else None,
            'elapsed': getattr(job, 'elapsed', None),
            'launch_type': getattr(job, 'launch_type', ''),
            'execution_node': getattr(job, 'execution_node', ''),
        },
    }

    for webhook in webhooks:
        send_outbound_webhook.delay(webhook.pk, job_data)
