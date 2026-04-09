"""Public branding lookup by host."""

import logging

from forge.main.tenancy.helpers import normalize_host

logger = logging.getLogger('forge.main.tenancy.branding')


def get_branding_for_host(host):
    """Return a dict describing the tenant for this host, or None."""
    normalized = normalize_host(host)
    if not normalized:
        return None

    from forge.main.models import Organization

    org = (
        Organization.objects
        .filter(tenant_custom_domain=normalized, is_tenant_root=True)
        .first()
    )
    if org is None:
        return None
    return {
        'tenant_id': org.pk,
        'name': org.name,
        'logo_url': org.tenant_logo_url or '',
        'primary_color': org.tenant_primary_color or '',
        'secondary_color': org.tenant_secondary_color or '',
        'contact_email': org.tenant_contact_email or '',
    }
