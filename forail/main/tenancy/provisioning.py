"""Tenant provisioning: create Organization + admin user + default Team."""

import logging

from django.contrib.auth.models import User
from django.db import transaction

from forail.main.tenancy.helpers import validate_provisioning_payload

logger = logging.getLogger('forail.main.tenancy.provisioning')


class ProvisioningError(Exception):
    def __init__(self, errors):
        self.errors = errors
        super().__init__('; '.join(errors))


@transaction.atomic
def provision_tenant(payload):
    """Create a tenant in a single transaction. Returns the new Organization."""
    errors = validate_provisioning_payload(payload)
    if errors:
        raise ProvisioningError(errors)

    from forail.main.models import Organization, Team
    from forail.main.models.tenancy import TenantUsage

    name = payload['name'].strip()
    quota = payload.get('quota') or {}
    branding = payload.get('branding') or {}

    org = Organization.objects.create(
        name=name,
        description=payload.get('description', '') or '',
        is_tenant_root=True,
        tenant_max_concurrent_jobs=quota.get('max_concurrent_jobs') or None,
        tenant_max_daily_launches=quota.get('max_daily_launches') or None,
        tenant_max_hosts=quota.get('max_hosts') or None,
        tenant_max_storage_mb=quota.get('max_storage_mb') or None,
        tenant_isolation_strict=bool(payload.get('isolation_strict', False)),
        tenant_logo_url=branding.get('logo_url', '') or '',
        tenant_primary_color=branding.get('primary_color', '') or '',
        tenant_secondary_color=branding.get('secondary_color', '') or '',
        tenant_custom_domain=branding.get('custom_domain', '') or '',
        tenant_contact_email=payload.get('contact_email', '') or '',
    )

    # Admin user.
    #
    # M6: refuse to silently reuse an existing username. Doing so both (a)
    # discards the supplied password (get_or_create only set it on create) and
    # (b) grants that pre-existing account — possibly another tenant's admin —
    # membership in this new org. Require an explicit attach_existing_admin
    # opt-in, and never accept a password we would throw away.
    admin_username = payload['admin_username']
    admin_email = payload['admin_email']
    admin_password = payload['admin_password']
    attach_existing = bool(payload.get('attach_existing_admin', False))

    existing = User.objects.filter(username=admin_username).first()
    if existing is not None:
        if not attach_existing:
            raise ProvisioningError([
                f'admin_username "{admin_username}" already exists; refusing to attach an '
                f'existing account to a new tenant. Pass attach_existing_admin=true to '
                f'intentionally reuse it (the supplied admin_password is then ignored).'
            ])
        user = existing
    else:
        user = User.objects.create(username=admin_username, email=admin_email, is_active=True)
        user.set_password(admin_password)
        user.save()

    # Grant admin role on the new Organization. Best-effort — role API may vary.
    try:
        org.admin_role.members.add(user)
    except Exception:  # pylint: disable=broad-except
        logger.exception('Failed to add user to admin_role for tenant %s', org.name)

    # Default Team
    try:
        Team.objects.create(
            name=f'{name} Default Team',
            organization=org,
        )
    except Exception:  # pylint: disable=broad-except
        logger.exception('Failed to create default team for tenant %s', org.name)

    # TenantUsage row
    TenantUsage.objects.get_or_create(organization=org)

    # Declare tenant Celery queue (best-effort, beat task will retry).
    try:
        from django.conf import settings
        if getattr(settings, 'TENANCY_DEDICATED_QUEUES_ENABLED', False):
            from forail.main.tenancy.queues import ensure_tenant_queue_exists
            ensure_tenant_queue_exists(org.pk)
    except Exception:  # pylint: disable=broad-except
        logger.debug('Failed to declare tenant queue for %s', org.name, exc_info=True)

    return org
