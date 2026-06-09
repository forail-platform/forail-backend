"""
Drift Detection Celery tasks for Forail.

Captures host fact snapshots after job runs, compares consecutive snapshots
to detect configuration drift, and evaluates alert rules.
"""

import hashlib
import json
import logging
from datetime import timedelta
from fnmatch import fnmatch

from celery import shared_task
from django.utils.timezone import now

logger = logging.getLogger('forail.main.tasks.drift')


# ---------------------------------------------------------------------------
# Severity ordering for threshold comparison
# ---------------------------------------------------------------------------

SEVERITY_ORDER = {'low': 0, 'medium': 1, 'high': 2, 'critical': 3}

# ---------------------------------------------------------------------------
# Fact path -> category + severity mapping
# ---------------------------------------------------------------------------

CATEGORY_MAP = {
    'ansible_pkg_mgr': ('packages', 'medium'),
    'ansible_packages': ('packages', 'medium'),
    'ansible_apparmor': ('kernel', 'medium'),
    'ansible_selinux': ('kernel', 'high'),
    'ansible_services': ('services', 'medium'),
    'ansible_service_mgr': ('services', 'low'),
    'ansible_user_dir': ('users_groups', 'high'),
    'ansible_user_id': ('users_groups', 'high'),
    'ansible_user_uid': ('users_groups', 'high'),
    'ansible_user_gid': ('users_groups', 'high'),
    'ansible_user_gecos': ('users_groups', 'medium'),
    'ansible_user_shell': ('users_groups', 'high'),
    'ansible_all_ipv4_addresses': ('network', 'high'),
    'ansible_all_ipv6_addresses': ('network', 'high'),
    'ansible_default_ipv4': ('network', 'high'),
    'ansible_default_ipv6': ('network', 'medium'),
    'ansible_interfaces': ('network', 'medium'),
    'ansible_dns': ('network', 'medium'),
    'ansible_domain': ('network', 'medium'),
    'ansible_fqdn': ('network', 'medium'),
    'ansible_hostname': ('network', 'low'),
    'ansible_mounts': ('mounts', 'medium'),
    'ansible_devices': ('mounts', 'low'),
    'ansible_kernel': ('kernel', 'critical'),
    'ansible_kernel_version': ('kernel', 'critical'),
    'ansible_cmdline': ('kernel', 'high'),
    'ansible_sysctl': ('kernel', 'high'),
    'ansible_architecture': ('kernel', 'low'),
    'ansible_bios_date': ('other', 'low'),
    'ansible_bios_version': ('other', 'low'),
    'ansible_date_time': ('other', 'low'),
    'ansible_distribution': ('other', 'low'),
    'ansible_distribution_version': ('other', 'medium'),
    'ansible_os_family': ('other', 'low'),
    'ansible_product_name': ('other', 'low'),
    'ansible_python': ('other', 'low'),
    'ansible_processor': ('other', 'low'),
    'ansible_memtotal_mb': ('other', 'low'),
    'ansible_swaptotal_mb': ('other', 'low'),
    'ansible_uptime_seconds': ('other', 'low'),
}


def _compute_facts_hash(facts):
    """Compute a deterministic SHA-256 hash of a facts dictionary."""
    raw = json.dumps(facts, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _classify_fact(key):
    """Return (category, severity) for a top-level fact key."""
    if key in CATEGORY_MAP:
        return CATEGORY_MAP[key]

    # Pattern-based fallback
    lower = key.lower()
    if 'package' in lower or 'pip' in lower or 'gem' in lower:
        return ('packages', 'medium')
    if 'service' in lower or 'systemd' in lower:
        return ('services', 'medium')
    if 'user' in lower or 'group' in lower or 'passwd' in lower:
        return ('users_groups', 'high')
    if 'ip' in lower or 'network' in lower or 'port' in lower or 'tcp' in lower or 'udp' in lower:
        return ('network', 'high')
    if 'mount' in lower or 'disk' in lower or 'fs' in lower or 'lvm' in lower:
        return ('mounts', 'medium')
    if 'kernel' in lower or 'sysctl' in lower or 'selinux' in lower:
        return ('kernel', 'high')
    return ('other', 'low')


def _diff_type(old_val, new_val):
    """Determine the diff type between two values."""
    if old_val is None:
        return 'added'
    if new_val is None:
        return 'removed'
    return 'changed'


def _summarize_change(key, old_val, new_val, diff_kind):
    """Generate a human-readable summary line."""
    if diff_kind == 'added':
        return f'{key}: added'
    if diff_kind == 'removed':
        return f'{key}: removed'

    # Summarize based on type
    if isinstance(old_val, list) and isinstance(new_val, list):
        added = set(str(x) for x in new_val) - set(str(x) for x in old_val)
        removed = set(str(x) for x in old_val) - set(str(x) for x in new_val)
        parts = []
        if added:
            parts.append(f'+{len(added)}')
        if removed:
            parts.append(f'-{len(removed)}')
        return f'{key}: {", ".join(parts)} items' if parts else f'{key}: changed'

    if isinstance(old_val, dict) and isinstance(new_val, dict):
        added_keys = set(new_val) - set(old_val)
        removed_keys = set(old_val) - set(new_val)
        changed_keys = {k for k in set(old_val) & set(new_val) if old_val[k] != new_val[k]}
        parts = []
        if added_keys:
            parts.append(f'+{len(added_keys)} keys')
        if removed_keys:
            parts.append(f'-{len(removed_keys)} keys')
        if changed_keys:
            parts.append(f'~{len(changed_keys)} keys')
        return f'{key}: {", ".join(parts)}' if parts else f'{key}: changed'

    return f'{key}: {old_val!r} -> {new_val!r}'


def compute_drift(old_facts, new_facts):
    """
    Compare two fact dictionaries and return a list of drift items.

    Each item is a dict with: fact_path, category, severity, summary, detail.
    Only compares top-level keys to avoid noise from deeply nested volatile data.
    """
    drifts = []
    all_keys = set(old_facts.keys()) | set(new_facts.keys())

    # Skip volatile keys that change every run
    SKIP_KEYS = {
        'ansible_date_time', 'ansible_uptime_seconds', 'ansible_local',
        'module_setup', 'gather_subset', 'ansible_fibre_channel_wwn',
    }

    for key in sorted(all_keys):
        if key in SKIP_KEYS:
            continue

        old_val = old_facts.get(key)
        new_val = new_facts.get(key)

        if old_val == new_val:
            continue

        diff_kind = _diff_type(old_val, new_val)
        category, severity = _classify_fact(key)
        summary = _summarize_change(key, old_val, new_val, diff_kind)

        # Truncate large values in detail to avoid bloating the DB
        def _truncate(val, max_len=2000):
            s = json.dumps(val, default=str)
            if len(s) > max_len:
                return json.loads(s[:max_len - 20] + '..."truncated"}')
            return val

        drifts.append({
            'fact_path': key,
            'category': category,
            'severity': severity,
            'summary': summary,
            'detail': {
                'before': _truncate(old_val),
                'after': _truncate(new_val),
                'diff_type': diff_kind,
            },
        })

    return drifts


# ---------------------------------------------------------------------------
# Celery Tasks
# ---------------------------------------------------------------------------

@shared_task(name='forail.main.tasks.drift.capture_fact_snapshot')
def capture_fact_snapshot(job_id):
    """
    Capture fact snapshots for all hosts affected by a job.

    Called from RunJob.post_run_hook after finish_fact_cache completes.
    Only creates snapshots when facts have actually changed (hash differs).
    """
    from forail.main.models import Host, Job

    try:
        job = Job.objects.select_related('inventory', 'inventory__organization').get(pk=job_id)
    except Job.DoesNotExist:
        logger.warning('capture_fact_snapshot: Job %s not found', job_id)
        return

    inventory = job.inventory
    if not inventory:
        return

    organization = getattr(inventory, 'organization', None)

    hosts = Host.objects.filter(
        inventory=inventory,
        ansible_facts_modified__isnull=False,
    ).exclude(ansible_facts={})

    created_count = 0
    for host in hosts.iterator(chunk_size=100):
        facts_hash = _compute_facts_hash(host.ansible_facts)

        # Check if the latest snapshot already has this hash
        from forail.main.models.drift import HostFactSnapshot
        latest = HostFactSnapshot.objects.filter(
            host=host,
        ).order_by('-captured_at').values_list('facts_hash', flat=True).first()

        if latest == facts_hash:
            continue

        snapshot = HostFactSnapshot.objects.create(
            host=host,
            job=job,
            inventory=inventory,
            organization=organization,
            facts=host.ansible_facts,
            facts_hash=facts_hash,
        )
        created_count += 1

        # Trigger drift comparison
        detect_drift.delay(snapshot.pk)

    logger.info(
        'capture_fact_snapshot: job=%s, created %d snapshots',
        job_id, created_count,
    )


@shared_task(name='forail.main.tasks.drift.detect_drift')
def detect_drift(snapshot_id):
    """
    Compare a new snapshot with the previous one for the same host.
    Creates DriftDetection records for each changed fact category.
    """
    from forail.main.models.drift import HostFactSnapshot, DriftDetection

    try:
        snapshot = HostFactSnapshot.objects.select_related('host', 'inventory').get(pk=snapshot_id)
    except HostFactSnapshot.DoesNotExist:
        logger.warning('detect_drift: Snapshot %s not found', snapshot_id)
        return

    # Find the previous snapshot for this host
    previous = HostFactSnapshot.objects.filter(
        host=snapshot.host,
        captured_at__lt=snapshot.captured_at,
    ).order_by('-captured_at').first()

    if not previous:
        # First snapshot for this host — baseline, no drift to detect
        logger.info('detect_drift: Snapshot %s is first baseline for host %s', snapshot_id, snapshot.host_id)
        return

    drifts = compute_drift(previous.facts, snapshot.facts)

    if not drifts:
        return

    drift_objects = []
    for d in drifts:
        drift_objects.append(DriftDetection(
            host=snapshot.host,
            inventory=snapshot.inventory,
            organization=snapshot.organization,
            snapshot_before=previous,
            snapshot_after=snapshot,
            job=snapshot.job,
            category=d['category'],
            severity=d['severity'],
            fact_path=d['fact_path'],
            summary=d['summary'],
            detail=d['detail'],
        ))

    DriftDetection.objects.bulk_create(drift_objects)

    logger.info(
        'detect_drift: snapshot=%s, host=%s, %d drift items created',
        snapshot_id, snapshot.host_id, len(drift_objects),
    )

    # Evaluate alert rules
    evaluate_drift_alerts.delay(snapshot.host_id)


@shared_task(name='forail.main.tasks.drift.evaluate_drift_alerts')
def evaluate_drift_alerts(host_id):
    """
    Evaluate all enabled DriftAlertRules against recent drift for a host.
    """
    from forail.main.models import Host
    from forail.main.models.drift import DriftAlertRule, DriftDetection, DriftAlert

    try:
        host = Host.objects.select_related('inventory', 'inventory__organization').get(pk=host_id)
    except Host.DoesNotExist:
        return

    inventory = host.inventory
    organization = getattr(inventory, 'organization', None)
    org_id = organization.pk if organization else None

    # Get all enabled rules that could match this host
    rules = DriftAlertRule.objects.filter(enabled=True)
    if org_id:
        rules = rules.filter(models_Q_org(org_id))
    rules = list(rules.select_related('notification_template'))

    for rule in rules:
        # Check inventory scope
        if rule.inventory_id and rule.inventory_id != host.inventory_id:
            continue

        # Check host filter
        if rule.host_filter and not fnmatch(host.name, rule.host_filter):
            continue

        # Check cooldown
        if rule.is_in_cooldown():
            continue

        # Count recent drifts within the window
        window_start = now() - timedelta(minutes=rule.threshold_window_minutes)
        drift_qs = DriftDetection.objects.filter(
            host=host,
            detected_at__gte=window_start,
        )

        # Filter by categories
        if rule.categories:
            drift_qs = drift_qs.filter(category__in=rule.categories)

        # Filter by minimum severity
        min_order = SEVERITY_ORDER.get(rule.severity_min, 0)
        severity_values = [k for k, v in SEVERITY_ORDER.items() if v >= min_order]
        drift_qs = drift_qs.filter(severity__in=severity_values)

        count = drift_qs.count()

        if count < rule.threshold_count:
            continue

        # Threshold met — create alert
        summary_parts = [f'{count} drift items detected on host {host.name}']
        categories_found = list(drift_qs.values_list('category', flat=True).distinct())
        if categories_found:
            summary_parts.append(f'Categories: {", ".join(categories_found)}')

        alert = DriftAlert.objects.create(
            alert_rule=rule,
            host=host,
            organization=organization,
            drift_count=count,
            summary='. '.join(summary_parts),
        )

        # Send notification
        if rule.notification_template:
            try:
                subject = f'[Forail] Drift Alert: {rule.name}'
                body = (
                    f'Drift alert triggered for host {host.name}.\n'
                    f'Rule: {rule.name}\n'
                    f'Drift count: {count} (threshold: {rule.threshold_count})\n'
                    f'Categories: {", ".join(categories_found)}\n'
                )
                rule.notification_template.send(subject, body)
                alert.notification_status = 'sent'
            except Exception as e:
                logger.exception('Failed to send drift alert notification: %s', e)
                alert.notification_status = 'failed'
                alert.notification_error = str(e)
            alert.save(update_fields=['notification_status', 'notification_error'])

        rule.record_trigger()

        logger.info(
            'evaluate_drift_alerts: rule=%s triggered for host=%s, drift_count=%d',
            rule.name, host.name, count,
        )


@shared_task(name='forail.main.tasks.drift.cleanup_old_snapshots')
def cleanup_old_snapshots(retention_days=90, min_keep=2):
    """
    Periodic cleanup: delete snapshots older than retention period.
    Always keeps at least min_keep snapshots per host.
    """
    from forail.main.models.drift import HostFactSnapshot

    cutoff = now() - timedelta(days=retention_days)

    # Get hosts with snapshots older than cutoff
    host_ids = HostFactSnapshot.objects.filter(
        captured_at__lt=cutoff,
    ).values_list('host_id', flat=True).distinct()

    deleted_total = 0
    for host_id in host_ids:
        # Keep the N most recent
        keep_ids = list(
            HostFactSnapshot.objects.filter(host_id=host_id)
            .order_by('-captured_at')
            .values_list('pk', flat=True)[:min_keep]
        )

        deleted, _ = HostFactSnapshot.objects.filter(
            host_id=host_id,
            captured_at__lt=cutoff,
        ).exclude(pk__in=keep_ids).delete()

        deleted_total += deleted

    logger.info('cleanup_old_snapshots: deleted %d snapshots', deleted_total)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def models_Q_org(org_id):
    """Return a Q object for org-scoped or null-org rules."""
    from django.db.models import Q
    return Q(organization_id=org_id) | Q(organization_id__isnull=True)
