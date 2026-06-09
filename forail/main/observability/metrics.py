"""Metric handle cache for Forail observability.

All functions are safe to call before ``init_observability`` has run: they
simply become no-ops until the SDK is initialized. Callers therefore never
need to guard with ``if OTEL_ENABLED``.
"""

import logging

logger = logging.getLogger('forail.main.observability.metrics')

_initialized = False
_meter = None
_handles = {}
_active_jobs_value = 0


def _get(name, factory):
    if not _initialized or _meter is None:
        return None
    h = _handles.get(name)
    if h is None:
        try:
            h = factory(_meter)
            _handles[name] = h
        except Exception as e:  # pylint: disable=broad-except
            logger.debug('metric create failed %s: %s', name, e)
            return None
    return h


def inc_jobs_launched(template_type='', status='ok'):
    c = _get(
        'forail_jobs_launched_total',
        lambda m: m.create_counter(
            'forail_jobs_launched_total',
            description='Number of jobs launched, by template type and status',
        ),
    )
    if c is None:
        return
    try:
        c.add(1, {'template_type': template_type or '', 'status': status or ''})
    except Exception:
        pass


def inc_jobs_blocked(gate):
    c = _get(
        'forail_jobs_blocked_total',
        lambda m: m.create_counter(
            'forail_jobs_blocked_total',
            description='Number of job launches blocked, by gate (policy|scanner)',
        ),
    )
    if c is None:
        return
    try:
        c.add(1, {'gate': gate or ''})
    except Exception:
        pass


def observe_job_duration(seconds, template_type=''):
    h = _get(
        'forail_job_duration_seconds',
        lambda m: m.create_histogram(
            'forail_job_duration_seconds',
            description='Wall-clock duration of Forail jobs, in seconds',
            unit='s',
        ),
    )
    if h is None:
        return
    try:
        h.record(float(seconds), {'template_type': template_type or ''})
    except Exception:
        pass


def inc_policy_evaluations(decision):
    c = _get(
        'forail_policy_evaluations_total',
        lambda m: m.create_counter(
            'forail_policy_evaluations_total',
            description='Number of OPA policy evaluations, by decision',
        ),
    )
    if c is None:
        return
    try:
        c.add(1, {'decision': decision or ''})
    except Exception:
        pass


def inc_tenant_quota_blocks(kind):
    c = _get(
        'forail_tenant_quota_blocks_total',
        lambda m: m.create_counter(
            'forail_tenant_quota_blocks_total',
            description='Number of tenant launches blocked by quota, by kind',
        ),
    )
    if c is None:
        return
    try:
        c.add(1, {'kind': kind or ''})
    except Exception:
        pass


def inc_scan_runs(status):
    c = _get(
        'forail_scan_runs_total',
        lambda m: m.create_counter(
            'forail_scan_runs_total',
            description='Number of IaC scanner runs, by status',
        ),
    )
    if c is None:
        return
    try:
        c.add(1, {'status': status or ''})
    except Exception:
        pass


def set_active_jobs(count):
    """Update the forail_active_jobs gauge.

    OpenTelemetry gauges are observable; we cache the latest value and
    register an observable callback lazily on first call.
    """
    global _active_jobs_value
    _active_jobs_value = int(count)
    if not _initialized or _meter is None:
        return
    if 'forail_active_jobs' in _handles:
        return
    try:
        def _callback(options):  # pragma: no cover - OTel internal path
            from opentelemetry.metrics import Observation
            yield Observation(_active_jobs_value, {})

        g = _meter.create_observable_gauge(
            'forail_active_jobs',
            callbacks=[_callback],
            description='Number of Forail jobs currently pending/waiting/running',
        )
        _handles['forail_active_jobs'] = g
    except Exception as e:  # pylint: disable=broad-except
        logger.debug('active_jobs gauge create failed: %s', e)
