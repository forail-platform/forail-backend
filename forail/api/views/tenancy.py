"""Multi-Tenancy v1 REST API views."""

import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated, IsAdminUser, AllowAny
from rest_framework.response import Response

from forail.api.generics import (
    ListAPIView,
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    APIView,
)
from forail.api.serializers.tenancy import (
    TenantSerializer,
    TenantProvisionSerializer,
    TenantUsageSerializer,
    TenantQuotaEventSerializer,
    TenantIsolationEventSerializer,
    BrandingPublicSerializer,
)
from forail.main.models import Organization
from forail.main.models.tenancy import TenantQuotaEvent, TenantIsolationEvent
from forail.main.tenancy.branding import get_branding_for_host

logger = logging.getLogger('forail.api.views.tenancy')


class TenantList(ListCreateAPIView):
    """GET /api/v2/tenants/ — list tenant orgs; POST — provision new tenant."""

    model = Organization
    permission_classes = [IsAuthenticated, IsAdminUser]
    ordering = ('name',)

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return TenantProvisionSerializer
        return TenantSerializer

    def get_queryset(self):
        return Organization.objects.filter(is_tenant_root=True).select_related('tenant_usage')

    def create(self, request, *args, **kwargs):
        serializer = TenantProvisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        from forail.main.tenancy.provisioning import provision_tenant, ProvisioningError
        try:
            org = provision_tenant(request.data)
        except ProvisioningError as e:
            return Response({'errors': e.errors}, status=status.HTTP_400_BAD_REQUEST)
        out = TenantSerializer(org, context={'request': request}).data
        return Response(out, status=status.HTTP_201_CREATED)


class TenantDetail(RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE /api/v2/tenants/{pk}/."""

    model = Organization
    serializer_class = TenantSerializer
    permission_classes = [IsAuthenticated, IsAdminUser]

    def get_queryset(self):
        return Organization.objects.filter(is_tenant_root=True).select_related('tenant_usage')

    def destroy(self, request, *args, **kwargs):
        confirm = request.query_params.get('confirm', '').lower() in ('1', 'true', 'yes')
        if not confirm:
            return Response(
                {'detail': 'Tenant deletion requires ?confirm=true.'},
                status=status.HTTP_409_CONFLICT,
            )
        org = self.get_object()
        try:
            from forail.main.models import UnifiedJob
            running = UnifiedJob.objects.filter(
                organization=org,
                status__in=['running', 'pending', 'waiting'],
            ).count()
        except Exception:  # pylint: disable=broad-except
            running = 0
        if running > 0:
            return Response(
                {'detail': f'Cannot delete tenant with {running} running/pending jobs.'},
                status=status.HTTP_409_CONFLICT,
            )
        org.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class TenantRecalculate(APIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    def post(self, request, *args, **kwargs):
        try:
            org = Organization.objects.get(pk=self.kwargs['pk'], is_tenant_root=True)
        except Organization.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        from forail.main.tenancy.usage import recalculate_tenant_usage
        usage = recalculate_tenant_usage(org)
        return Response(TenantUsageSerializer(usage).data)


class TenantQuotaEventList(ListAPIView):
    model = TenantQuotaEvent
    serializer_class = TenantQuotaEventSerializer
    permission_classes = [IsAuthenticated, IsAdminUser]
    ordering = ('-created',)

    def get_queryset(self):
        qs = TenantQuotaEvent.objects.all()
        p = self.request.query_params
        if p.get('organization'):
            qs = qs.filter(organization_id=p['organization'])
        if p.get('quota_kind'):
            qs = qs.filter(quota_kind=p['quota_kind'])
        if p.get('decision'):
            qs = qs.filter(decision=p['decision'])
        if p.get('since'):
            qs = qs.filter(created__gte=p['since'])
        return qs


class TenantIsolationEventList(ListAPIView):
    """GET /api/v2/tenant_isolation_events/ — filterable isolation audit log."""

    model = TenantIsolationEvent
    serializer_class = TenantIsolationEventSerializer
    permission_classes = [IsAuthenticated, IsAdminUser]
    ordering = ('-created',)

    def get_queryset(self):
        qs = TenantIsolationEvent.objects.all()
        p = self.request.query_params
        if p.get('user'):
            qs = qs.filter(user_id=p['user'])
        if p.get('user_organization'):
            qs = qs.filter(user_organization_id=p['user_organization'])
        if p.get('accessed_organization'):
            qs = qs.filter(accessed_organization_id=p['accessed_organization'])
        if p.get('blocked'):
            qs = qs.filter(blocked=p['blocked'].lower() in ('1', 'true', 'yes'))
        if p.get('since'):
            qs = qs.filter(created__gte=p['since'])
        return qs


class BrandingByHost(APIView):
    """GET /api/v2/branding/?host=... — PUBLIC, no auth."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, *args, **kwargs):
        host = request.query_params.get('host', '')
        data = get_branding_for_host(host)
        if data is None:
            return Response(
                {'detail': 'No tenant branding for host.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(BrandingPublicSerializer(data).data)
