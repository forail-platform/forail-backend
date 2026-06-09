"""Audit Event API views."""

import csv
import io

from django.http import StreamingHttpResponse
from django.utils.translation import gettext_lazy as _

from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from forail.api.generics import GenericAPIView, ListAPIView, RetrieveAPIView
from forail.api.serializers.audit import AuditEventSerializer, AuditEventSIEMSerializer
from forail.main.models.audit import AuditEvent


class AuditEventList(ListAPIView):
    """
    List audit events with filtering.

    Supports query parameters:
    - category: auth, credential_access, permission_change, resource_change, system
    - severity: info, warning, critical
    - action: specific action string
    - actor__username: filter by actor username
    - resource_type: filter by resource type
    - resource_id: filter by resource ID
    - timestamp__gte: events after this ISO datetime
    - timestamp__lte: events before this ISO datetime
    - organization: filter by organization ID
    - format: 'json' (default), 'csv', 'siem'
    """
    model = AuditEvent
    serializer_class = AuditEventSerializer
    permission_classes = [IsAuthenticated]
    ordering = ('-timestamp',)

    def get_queryset(self):
        qs = AuditEvent.objects.all()

        # Only superusers and auditors see all events
        user = self.request.user
        if not (user.is_superuser or getattr(user, 'is_system_auditor', False)):
            # Non-admin users only see events in their organizations
            user_org_ids = user.organizations.values_list('id', flat=True)
            qs = qs.filter(organization_id__in=user_org_ids)

        # Apply filters
        params = self.request.query_params
        if params.get('category'):
            qs = qs.filter(category=params['category'])
        if params.get('severity'):
            qs = qs.filter(severity=params['severity'])
        if params.get('action'):
            qs = qs.filter(action=params['action'])
        if params.get('actor__username'):
            qs = qs.filter(actor_username=params['actor__username'])
        if params.get('resource_type'):
            qs = qs.filter(resource_type=params['resource_type'])
        if params.get('resource_id'):
            qs = qs.filter(resource_id=params['resource_id'])
        if params.get('timestamp__gte'):
            qs = qs.filter(timestamp__gte=params['timestamp__gte'])
        if params.get('timestamp__lte'):
            qs = qs.filter(timestamp__lte=params['timestamp__lte'])
        if params.get('organization'):
            qs = qs.filter(organization_id=params['organization'])

        return qs

    def list(self, request, *args, **kwargs):
        fmt = request.query_params.get('format', 'json')

        if fmt == 'csv':
            return self._export_csv(request)
        elif fmt == 'siem':
            return self._export_siem(request)

        return super().list(request, *args, **kwargs)

    def _export_csv(self, request):
        qs = self.get_queryset()[:10000]  # Limit CSV export

        def csv_rows():
            output = io.StringIO()
            writer = csv.writer(output)
            # Header
            header = [
                'id', 'timestamp', 'actor_username', 'actor_ip', 'category',
                'severity', 'action', 'description', 'resource_type',
                'resource_id', 'resource_name', 'action_node',
            ]
            writer.writerow(header)
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)

            for event in qs.iterator():
                writer.writerow([
                    event.id,
                    event.timestamp.isoformat(),
                    event.actor_username,
                    event.actor_ip or '',
                    event.category,
                    event.severity,
                    event.action,
                    event.description,
                    event.resource_type,
                    event.resource_id or '',
                    event.resource_name,
                    event.action_node,
                ])
                yield output.getvalue()
                output.seek(0)
                output.truncate(0)

        response = StreamingHttpResponse(csv_rows(), content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="audit_events.csv"'
        return response

    def _export_siem(self, request):
        qs = self.get_queryset()
        # Use pagination for SIEM export
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = AuditEventSIEMSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = AuditEventSIEMSerializer(qs, many=True)
        return Response(serializer.data)


class AuditEventDetail(RetrieveAPIView):
    model = AuditEvent
    serializer_class = AuditEventSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or getattr(user, 'is_system_auditor', False):
            return AuditEvent.objects.all()
        user_org_ids = user.organizations.values_list('id', flat=True)
        return AuditEvent.objects.filter(organization_id__in=user_org_ids)
