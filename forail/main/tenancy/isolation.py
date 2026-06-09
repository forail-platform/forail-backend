"""Cross-tenant isolation middleware — Multi-Tenancy v2.

Two responsibilities:

1. **RLS gate** (``__call__``): Sets ``forail.current_tenant_id`` Postgres
   session variable so Row-Level Security policies filter rows.

2. **Strict isolation gate** (``process_view``): When a tenant has
   ``tenant_isolation_strict=True`` AND ``TENANCY_STRICT_ISOLATION_ENABLED``
   is True globally, cross-tenant API access is **blocked** (HTTP 403) and
   a ``TenantIsolationEvent(blocked=True)`` is emitted.  Otherwise the
   event is emitted with ``blocked=False`` (audit-only).

Behaviour matrix:
    - ``TENANCY_ENABLED=False``  → both gates are no-op
    - ``TENANCY_RLS_ENABLED=False`` → RLS gate is no-op
    - Unauthenticated request → both gates are no-op
    - Superuser → both gates are no-op (sees everything)
    - Exempt paths (login, branding, config, tenants admin) → strict gate skipped
"""

import logging

from django.conf import settings
from django.http import JsonResponse

from forail.main.tenancy.rls import set_tenant_id, clear_tenant_id
from forail.main.tenancy.helpers import (
    should_exempt_isolation,
    make_isolation_decision,
)

logger = logging.getLogger('forail.main.tenancy.isolation')


class TenantIsolationMiddleware:
    """Set Postgres ``forail.current_tenant_id`` per request for RLS and
    enforce strict cross-tenant isolation when configured."""

    def __init__(self, get_response):
        self.get_response = get_response

    # ------------------------------------------------------------------
    # Gate 1: RLS — set session variable
    # ------------------------------------------------------------------

    def __call__(self, request):
        tenant_org = None
        try:
            tenant_org = self._resolve_tenant_org(request)
            if tenant_org is not None:
                set_tenant_id(tenant_org.pk)
                # Stash on request for process_view (strict gate).
                request._tenant_org = tenant_org
        except Exception:
            logger.debug('TenantIsolationMiddleware: failed to set tenant id', exc_info=True)

        try:
            response = self.get_response(request)
        finally:
            if tenant_org is not None:
                try:
                    clear_tenant_id()
                except Exception:
                    pass

        return response

    # ------------------------------------------------------------------
    # Gate 2: Strict isolation — block cross-tenant access
    # ------------------------------------------------------------------

    def process_view(self, request, view_func, view_args, view_kwargs):
        """Called by Django after URL resolution but before the view.

        Returns ``None`` to proceed normally, or an ``HttpResponse`` to
        short-circuit.
        """
        if not getattr(settings, 'TENANCY_ENABLED', False):
            return None

        user = getattr(request, 'user', None)
        if user is None or not getattr(user, 'is_authenticated', False):
            return None
        if getattr(user, 'is_superuser', False):
            return None

        # Exempt paths skip isolation checks entirely.
        if should_exempt_isolation(getattr(request, 'path', '')):
            return None

        tenant_org = getattr(request, '_tenant_org', None)
        if tenant_org is None:
            return None

        # Resolve the organization of the target resource.
        target_org_id = self._resolve_target_org_id(request, view_func, view_kwargs)
        if target_org_id is None:
            # Cannot determine target org — allow (fail-open for audit).
            return None

        is_cross_tenant = (int(target_org_id) != int(tenant_org.pk))
        user_org_strict = getattr(tenant_org, 'tenant_isolation_strict', False)
        global_strict = getattr(settings, 'TENANCY_STRICT_ISOLATION_ENABLED', False)

        should_block, should_audit = make_isolation_decision(
            user_org_strict, global_strict, is_cross_tenant,
        )

        if should_audit:
            event = self._emit_isolation_event(
                request, tenant_org, target_org_id, should_block,
            )
            event_id = getattr(event, 'pk', None)
        else:
            event_id = None

        if should_block:
            logger.warning(
                'tenant_isolation: BLOCKED user=%s org=%s target_org=%s path=%s',
                getattr(user, 'pk', None), tenant_org.pk, target_org_id,
                getattr(request, 'path', ''),
            )
            return JsonResponse(
                {
                    'detail': 'Cross-tenant access denied.',
                    'isolation_event_id': event_id,
                },
                status=403,
            )

        return None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_tenant_org(request):
        """Return the user's primary tenant Organization, or None."""
        if not getattr(settings, 'TENANCY_ENABLED', False):
            return None
        if not getattr(settings, 'TENANCY_RLS_ENABLED', False):
            return None

        user = getattr(request, 'user', None)
        if user is None or not getattr(user, 'is_authenticated', False):
            return None
        if getattr(user, 'is_superuser', False):
            return None

        try:
            orgs = list(
                user.organizations.filter(is_tenant_root=True)
                .only('pk', 'is_tenant_root', 'tenant_isolation_strict')[:1]
            )
        except Exception:
            logger.debug('_resolve_tenant_org: org lookup failed', exc_info=True)
            return None

        return orgs[0] if orgs else None

    @staticmethod
    def _resolve_target_org_id(request, view_func, view_kwargs):
        """Best-effort resolution of the target resource's organization_id.

        Strategy:
        1. If the view class has a ``model`` attribute and kwargs contain
           ``pk``, look up the object and read ``organization_id`` (direct)
           or ``inventory.organization_id`` (indirect for hosts).
        2. If ``organization`` is in kwargs (sub-resource views), use it
           directly.

        Returns an int org_id or None.
        """
        # Strategy A: explicit org in URL kwargs (e.g. /organizations/{pk}/...).
        org_kwarg = view_kwargs.get('organization')
        if org_kwarg is not None:
            try:
                return int(org_kwarg)
            except (TypeError, ValueError):
                pass

        pk = view_kwargs.get('pk')
        if pk is None:
            return None

        # Strategy B: resolve from the view's model.
        view_cls = getattr(view_func, 'cls', None) or getattr(view_func, 'view_class', None)
        if view_cls is None:
            return None

        model = getattr(view_cls, 'model', None)
        if model is None:
            return None

        try:
            # Direct organization_id on the model.
            if hasattr(model, 'organization_id') or hasattr(model, 'organization'):
                obj = model.objects.filter(pk=pk).values_list('organization_id', flat=True).first()
                if obj is not None:
                    return int(obj) if obj else None

            # Indirect: Host → Inventory → Organization.
            from forail.main.models import Host
            if model is Host or (hasattr(model, '__name__') and model.__name__ == 'Host'):
                from forail.main.models import Inventory
                inv_id = Host.objects.filter(pk=pk).values_list('inventory_id', flat=True).first()
                if inv_id:
                    org_id = Inventory.objects.filter(pk=inv_id).values_list('organization_id', flat=True).first()
                    return int(org_id) if org_id else None
        except Exception:
            logger.debug('_resolve_target_org_id: lookup failed', exc_info=True)

        return None

    @staticmethod
    def _emit_isolation_event(request, user_org, target_org_id, blocked):
        """Create a TenantIsolationEvent record. Returns the event or None."""
        try:
            from forail.main.models.tenancy import TenantIsolationEvent
            user = getattr(request, 'user', None)
            event = TenantIsolationEvent.objects.create(
                user=user if getattr(user, 'is_authenticated', False) else None,
                user_organization=user_org,
                accessed_organization_id=int(target_org_id),
                resource_type=_get_resource_type(request),
                resource_id=_get_resource_id(request),
                request_path=getattr(request, 'path', '')[:1024],
                blocked=blocked,
            )
            return event
        except Exception:
            logger.exception('Failed to emit TenantIsolationEvent')
            return None


def _get_resource_type(request):
    """Extract a short resource type string from the request path."""
    # e.g. /api/v2/inventories/5/ → 'inventories'
    path = getattr(request, 'path', '') or ''
    parts = [p for p in path.strip('/').split('/') if p]
    # Expected: ['api', 'v2', 'inventories', '5']
    if len(parts) >= 3 and parts[0] == 'api':
        return parts[2][:64]
    return ''


def _get_resource_id(request):
    """Extract the numeric resource ID from the request path, if present."""
    path = getattr(request, 'path', '') or ''
    parts = [p for p in path.strip('/').split('/') if p]
    if len(parts) >= 4 and parts[0] == 'api':
        try:
            return int(parts[3])
        except (ValueError, IndexError):
            pass
    return None
