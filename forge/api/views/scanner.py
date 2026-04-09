"""IaC Scanner API views."""

import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from forge.api.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    ListAPIView,
    RetrieveAPIView,
    APIView,
)
from forge.api.serializers.scanner import (
    ScannerSerializer,
    ScannerListSerializer,
    ScanResultSerializer,
    ScanResultListSerializer,
)
from forge.main.models.scanner import Scanner, ScanResult

logger = logging.getLogger('forge.api.views.scanner')


def _org_filtered(qs, user, org_field='organization_id'):
    if user.is_superuser or getattr(user, 'is_system_auditor', False):
        return qs
    user_org_ids = user.organizations.values_list('id', flat=True)
    from django.db.models import Q
    return qs.filter(Q(**{f'{org_field}__in': user_org_ids}) | Q(**{f'{org_field}__isnull': True}))


class ScannerList(ListCreateAPIView):
    model = Scanner
    permission_classes = [IsAuthenticated]
    ordering = ('name',)

    def get_serializer_class(self):
        if self.request.method == 'GET':
            return ScannerListSerializer
        return ScannerSerializer

    def get_queryset(self):
        qs = Scanner.objects.all()
        qs = _org_filtered(qs, self.request.user)
        params = self.request.query_params
        if params.get('enabled') is not None:
            v = params['enabled'].lower()
            if v in ('true', '1'):
                qs = qs.filter(enabled=True)
            elif v in ('false', '0'):
                qs = qs.filter(enabled=False)
        if params.get('search'):
            qs = qs.filter(name__icontains=params['search'])
        if params.get('organization'):
            qs = qs.filter(organization_id=params['organization'])
        if params.get('tool'):
            qs = qs.filter(tool=params['tool'])
        if params.get('applies_to'):
            qs = qs.filter(applies_to__contains=[params['applies_to']])
        return qs


class ScannerDetail(RetrieveUpdateDestroyAPIView):
    model = Scanner
    serializer_class = ScannerSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return _org_filtered(Scanner.objects.all(), self.request.user)


class ScannerToggle(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        action = self.kwargs.get('action')
        try:
            scanner = _org_filtered(Scanner.objects.all(), request.user).get(pk=self.kwargs['pk'])
        except Scanner.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        scanner.enabled = (action == 'enable')
        scanner.save(update_fields=['enabled', 'modified'])
        return Response({'enabled': scanner.enabled})


class ScanResultList(ListAPIView):
    model = ScanResult
    permission_classes = [IsAuthenticated]
    ordering = ('-created',)

    def get_serializer_class(self):
        return ScanResultListSerializer

    def get_queryset(self):
        qs = ScanResult.objects.select_related('scanner', 'unified_job', 'triggered_by').all()
        qs = _org_filtered(qs, self.request.user)
        params = self.request.query_params
        if params.get('status'):
            qs = qs.filter(status=params['status'])
        if params.get('scanner'):
            qs = qs.filter(scanner_id=params['scanner'])
        if params.get('unified_job'):
            qs = qs.filter(unified_job_id=params['unified_job'])
        if params.get('since'):
            qs = qs.filter(created__gte=params['since'])
        return qs


class ScanResultDetail(RetrieveAPIView):
    model = ScanResult
    serializer_class = ScanResultSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return _org_filtered(
            ScanResult.objects.prefetch_related('findings').all(),
            self.request.user,
        )
