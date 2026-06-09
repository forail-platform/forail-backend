"""Drift Detection API views."""

import csv
import io
import logging
from datetime import timedelta

from django.db.models import Count
from django.http import HttpResponse
from django.utils.timezone import now

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from forail.api.generics import ListCreateAPIView, RetrieveUpdateDestroyAPIView, ListAPIView, RetrieveAPIView, APIView
from forail.api.serializers.drift import (
    HostFactSnapshotSerializer,
    HostFactSnapshotListSerializer,
    DriftDetectionSerializer,
    DriftDetectionListSerializer,
    DriftAlertRuleSerializer,
    DriftAlertRuleListSerializer,
    DriftAlertSerializer,
    DriftAlertListSerializer,
)
from forail.main.models.drift import HostFactSnapshot, DriftDetection, DriftAlertRule, DriftAlert

logger = logging.getLogger('forail.api.views.drift')


def _org_filtered_qs(qs, user, org_field='organization_id'):
    """Apply organization-based access control."""
    if user.is_superuser or getattr(user, 'is_system_auditor', False):
        return qs
    user_org_ids = user.organizations.values_list('id', flat=True)
    return qs.filter(**{f'{org_field}__in': user_org_ids})


# ---------------------------------------------------------------------------
# HostFactSnapshot (read-only)
# ---------------------------------------------------------------------------

class HostFactSnapshotList(ListAPIView):
    model = HostFactSnapshot
    permission_classes = [IsAuthenticated]
    ordering = ('-captured_at',)

    def get_serializer_class(self):
        return HostFactSnapshotListSerializer

    def get_queryset(self):
        qs = HostFactSnapshot.objects.all()
        qs = _org_filtered_qs(qs, self.request.user)

        params = self.request.query_params
        if params.get('host'):
            qs = qs.filter(host_id=params['host'])
        if params.get('inventory'):
            qs = qs.filter(inventory_id=params['inventory'])
        if params.get('job'):
            qs = qs.filter(job_id=params['job'])
        return qs


class HostFactSnapshotDetail(RetrieveAPIView):
    model = HostFactSnapshot
    serializer_class = HostFactSnapshotSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return _org_filtered_qs(HostFactSnapshot.objects.all(), self.request.user)


# ---------------------------------------------------------------------------
# DriftDetection (read-only + acknowledge)
# ---------------------------------------------------------------------------

class DriftDetectionList(ListAPIView):
    model = DriftDetection
    permission_classes = [IsAuthenticated]
    ordering = ('-detected_at',)

    def get_serializer_class(self):
        return DriftDetectionListSerializer

    def get_queryset(self):
        qs = DriftDetection.objects.select_related('host').all()
        qs = _org_filtered_qs(qs, self.request.user)

        params = self.request.query_params
        if params.get('host'):
            qs = qs.filter(host_id=params['host'])
        if params.get('inventory'):
            qs = qs.filter(inventory_id=params['inventory'])
        if params.get('category'):
            qs = qs.filter(category=params['category'])
        if params.get('severity'):
            qs = qs.filter(severity=params['severity'])
        if params.get('acknowledged') is not None:
            ack = params['acknowledged'].lower()
            if ack in ('true', '1'):
                qs = qs.filter(acknowledged=True)
            elif ack in ('false', '0'):
                qs = qs.filter(acknowledged=False)
        if params.get('detected_at__gte'):
            qs = qs.filter(detected_at__gte=params['detected_at__gte'])
        if params.get('detected_at__lte'):
            qs = qs.filter(detected_at__lte=params['detected_at__lte'])
        if params.get('search'):
            qs = qs.filter(fact_path__icontains=params['search'])
        return qs


class DriftDetectionDetail(RetrieveAPIView):
    model = DriftDetection
    serializer_class = DriftDetectionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return _org_filtered_qs(
            DriftDetection.objects.select_related('host').all(),
            self.request.user,
        )


class DriftDetectionAcknowledge(APIView):
    """Mark a drift detection as acknowledged."""
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        pk = self.kwargs['pk']
        qs = _org_filtered_qs(DriftDetection.objects.all(), request.user)
        try:
            drift = qs.get(pk=pk)
        except DriftDetection.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        drift.acknowledged = True
        drift.acknowledged_by = request.user
        drift.acknowledged_at = now()
        drift.save(update_fields=['acknowledged', 'acknowledged_by', 'acknowledged_at'])

        return Response({'acknowledged': True})


# ---------------------------------------------------------------------------
# DriftAlertRule (CRUD)
# ---------------------------------------------------------------------------

class DriftAlertRuleList(ListCreateAPIView):
    model = DriftAlertRule
    permission_classes = [IsAuthenticated]
    ordering = ('name',)

    def get_serializer_class(self):
        if self.request.method == 'GET':
            return DriftAlertRuleListSerializer
        return DriftAlertRuleSerializer

    def get_queryset(self):
        qs = DriftAlertRule.objects.all()
        qs = _org_filtered_qs(qs, self.request.user)

        params = self.request.query_params
        if params.get('organization'):
            qs = qs.filter(organization_id=params['organization'])
        if params.get('search'):
            qs = qs.filter(name__icontains=params['search'])
        if params.get('enabled') is not None:
            enabled_val = params['enabled'].lower()
            if enabled_val in ('true', '1'):
                qs = qs.filter(enabled=True)
            elif enabled_val in ('false', '0'):
                qs = qs.filter(enabled=False)
        return qs


class DriftAlertRuleDetail(RetrieveUpdateDestroyAPIView):
    model = DriftAlertRule
    serializer_class = DriftAlertRuleSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return _org_filtered_qs(DriftAlertRule.objects.all(), self.request.user)


class DriftAlertRuleToggle(APIView):
    """Enable or disable a DriftAlertRule."""
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        pk = self.kwargs['pk']
        action = self.kwargs.get('action')

        qs = _org_filtered_qs(DriftAlertRule.objects.all(), request.user)
        try:
            rule = qs.get(pk=pk)
        except DriftAlertRule.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        rule.enabled = (action == 'enable')
        rule.save(update_fields=['enabled'])

        return Response({'enabled': rule.enabled})


# ---------------------------------------------------------------------------
# DriftAlert (read-only)
# ---------------------------------------------------------------------------

class DriftAlertList(ListAPIView):
    model = DriftAlert
    permission_classes = [IsAuthenticated]
    ordering = ('-created',)

    def get_serializer_class(self):
        return DriftAlertListSerializer

    def get_queryset(self):
        qs = DriftAlert.objects.all()
        qs = _org_filtered_qs(qs, self.request.user)

        params = self.request.query_params
        if params.get('alert_rule'):
            qs = qs.filter(alert_rule_id=params['alert_rule'])
        if params.get('host'):
            qs = qs.filter(host_id=params['host'])
        if params.get('notification_status'):
            qs = qs.filter(notification_status=params['notification_status'])
        return qs


class DriftAlertDetail(RetrieveAPIView):
    model = DriftAlert
    serializer_class = DriftAlertSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return _org_filtered_qs(DriftAlert.objects.all(), self.request.user)


# ---------------------------------------------------------------------------
# DriftSummary (dashboard widget)
# ---------------------------------------------------------------------------

class DriftSummaryView(APIView):
    """Aggregate drift statistics for the dashboard."""
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        qs = _org_filtered_qs(DriftDetection.objects.all(), request.user)

        # Default: last 7 days
        days = int(request.query_params.get('days', 7))
        since = now() - timedelta(days=days)
        qs = qs.filter(detected_at__gte=since)

        total = qs.count()
        unack = qs.filter(acknowledged=False).count()
        hosts_with_drift = qs.values('host').distinct().count()

        by_category = {}
        for row in qs.values('category').annotate(count=Count('id')):
            by_category[row['category']] = row['count']

        by_severity = {}
        for row in qs.values('severity').annotate(count=Count('id')):
            by_severity[row['severity']] = row['count']

        return Response({
            'total_hosts_with_drift': hosts_with_drift,
            'total_drift_items': total,
            'unacknowledged_count': unack,
            'by_category': by_category,
            'by_severity': by_severity,
        })


# ---------------------------------------------------------------------------
# DriftCompare (compare two snapshots)
# ---------------------------------------------------------------------------

class DriftCompareView(APIView):
    """Compare two fact snapshots and return the diff."""
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        snapshot_a_id = request.data.get('snapshot_a')
        snapshot_b_id = request.data.get('snapshot_b')

        if not snapshot_a_id or not snapshot_b_id:
            return Response(
                {'error': 'Both snapshot_a and snapshot_b are required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        qs = _org_filtered_qs(HostFactSnapshot.objects.all(), request.user)

        try:
            snap_a = qs.get(pk=snapshot_a_id)
            snap_b = qs.get(pk=snapshot_b_id)
        except HostFactSnapshot.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        from forail.main.tasks.drift import compute_drift
        drifts = compute_drift(snap_a.facts, snap_b.facts)

        return Response({
            'snapshot_a': snapshot_a_id,
            'snapshot_b': snapshot_b_id,
            'diff_count': len(drifts),
            'diffs': drifts,
        })


# ---------------------------------------------------------------------------
# DriftExport (CSV compliance report)
# ---------------------------------------------------------------------------

class DriftExportView(APIView):
    """Export drift detections as CSV for compliance reporting."""
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        qs = _org_filtered_qs(
            DriftDetection.objects.select_related('host').all(),
            request.user,
        )

        params = request.query_params
        if params.get('host'):
            qs = qs.filter(host_id=params['host'])
        if params.get('inventory'):
            qs = qs.filter(inventory_id=params['inventory'])
        if params.get('category'):
            qs = qs.filter(category=params['category'])
        if params.get('severity'):
            qs = qs.filter(severity=params['severity'])
        if params.get('date_from'):
            qs = qs.filter(detected_at__gte=params['date_from'])
        if params.get('date_to'):
            qs = qs.filter(detected_at__lte=params['date_to'])

        qs = qs.order_by('-detected_at')[:5000]

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            'ID', 'Host', 'Detected At', 'Category', 'Severity',
            'Fact Path', 'Summary', 'Diff Type', 'Acknowledged',
        ])

        for d in qs:
            host_name = d.host.name if d.host else ''
            diff_type = d.detail.get('diff_type', '') if isinstance(d.detail, dict) else ''
            writer.writerow([
                d.pk,
                host_name,
                d.detected_at.isoformat(),
                d.category,
                d.severity,
                d.fact_path,
                d.summary,
                diff_type,
                'Yes' if d.acknowledged else 'No',
            ])

        response = HttpResponse(output.getvalue(), content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="drift_report.csv"'
        return response


# ---------------------------------------------------------------------------
# Host Drift History (nested under hosts)
# ---------------------------------------------------------------------------

class HostDriftHistory(ListAPIView):
    """List drift detections for a specific host."""
    serializer_class = DriftDetectionListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        host_pk = self.kwargs['pk']
        qs = DriftDetection.objects.filter(host_id=host_pk).select_related('host')
        return _org_filtered_qs(qs, self.request.user)
