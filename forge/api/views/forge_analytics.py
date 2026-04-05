"""Forge Analytics views — local analytics computed from existing job data."""

import dateutil.relativedelta
import logging

from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import Trunc
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from forge.api.generics import APIView
from forge.api.versioning import reverse
from forge.main.access import get_user_queryset
from forge.main import models

logger = logging.getLogger('forge.api.views.forge_analytics')


def _get_date_range(request):
    """Parse period or explicit date range from query params."""
    period = request.query_params.get('period', 'month')
    end = now()

    if period == 'week':
        start = end - dateutil.relativedelta.relativedelta(weeks=1)
    elif period == 'two_weeks':
        start = end - dateutil.relativedelta.relativedelta(weeks=2)
    elif period == 'month':
        start = end - dateutil.relativedelta.relativedelta(months=1)
    elif period == 'quarter':
        start = end - dateutil.relativedelta.relativedelta(months=3)
    elif period == 'year':
        start = end - dateutil.relativedelta.relativedelta(years=1)
    else:
        start = end - dateutil.relativedelta.relativedelta(months=1)

    return start, end


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------

class ForgeAnalyticsRootView(APIView):
    """Links to all analytics endpoints."""
    permission_classes = [IsAuthenticated]
    name = _('Forge Analytics')

    def get(self, request, format=None):
        return Response({
            'job_trends': reverse('api:forge_analytics_job_trends', request=request),
            'success_rate': reverse('api:forge_analytics_success_rate', request=request),
            'top_templates': reverse('api:forge_analytics_top_templates', request=request),
            'busiest_hosts': reverse('api:forge_analytics_busiest_hosts', request=request),
            'host_coverage': reverse('api:forge_analytics_host_coverage', request=request),
            'failure_analysis': reverse('api:forge_analytics_failure_analysis', request=request),
            'time_savings': reverse('api:forge_analytics_time_savings', request=request),
        })


# ---------------------------------------------------------------------------
# Job Duration Trends
# ---------------------------------------------------------------------------

class JobTrendsView(APIView):
    """Job duration trends over time."""
    permission_classes = [IsAuthenticated]

    def get(self, request, format=None):
        start, end = _get_date_range(request)
        granularity = request.query_params.get('granularity', 'day')

        jobs = get_user_queryset(request.user, models.Job).filter(
            finished__range=(start, end),
            status__in=('successful', 'failed', 'error', 'canceled'),
        )

        rows = (
            jobs
            .annotate(d=Trunc('finished', granularity, tzinfo=end.tzinfo))
            .values('d')
            .annotate(
                job_count=Count('id'),
                avg_duration=Avg('elapsed'),
                successful=Count('id', filter=Q(status='successful')),
                failed=Count('id', filter=Q(status='failed')),
            )
            .order_by('d')
        )

        data = []
        for row in rows:
            data.append({
                'date': row['d'].isoformat() if row['d'] else None,
                'job_count': row['job_count'],
                'avg_duration': round(float(row['avg_duration'] or 0), 1),
                'successful': row['successful'],
                'failed': row['failed'],
            })

        return Response(data)


# ---------------------------------------------------------------------------
# Success Rate Over Time
# ---------------------------------------------------------------------------

class SuccessRateView(APIView):
    """Success/failure rates over time."""
    permission_classes = [IsAuthenticated]

    def get(self, request, format=None):
        start, end = _get_date_range(request)
        granularity = request.query_params.get('granularity', 'day')

        jobs = get_user_queryset(request.user, models.Job).filter(
            finished__range=(start, end),
            status__in=('successful', 'failed', 'error', 'canceled'),
        )

        rows = (
            jobs
            .annotate(d=Trunc('finished', granularity, tzinfo=end.tzinfo))
            .values('d')
            .annotate(
                total=Count('id'),
                successful=Count('id', filter=Q(status='successful')),
                failed=Count('id', filter=Q(status='failed')),
                error=Count('id', filter=Q(status='error')),
                canceled=Count('id', filter=Q(status='canceled')),
            )
            .order_by('d')
        )

        data = []
        for row in rows:
            total = row['total'] or 1
            data.append({
                'date': row['d'].isoformat() if row['d'] else None,
                'total': row['total'],
                'successful': row['successful'],
                'failed': row['failed'],
                'error': row['error'],
                'canceled': row['canceled'],
                'success_rate': round(row['successful'] / total * 100, 1),
            })

        return Response(data)


# ---------------------------------------------------------------------------
# Top Templates
# ---------------------------------------------------------------------------

class TopTemplatesView(APIView):
    """Most-used job templates."""
    permission_classes = [IsAuthenticated]

    def get(self, request, format=None):
        start, end = _get_date_range(request)
        limit = int(request.query_params.get('limit', 10))

        jobs = get_user_queryset(request.user, models.Job).filter(
            finished__range=(start, end),
            job_template__isnull=False,
        )

        rows = (
            jobs
            .values('job_template__id', 'job_template__name')
            .annotate(
                run_count=Count('id'),
                avg_duration=Avg('elapsed'),
                successful=Count('id', filter=Q(status='successful')),
            )
            .order_by('-run_count')[:limit]
        )

        data = []
        for row in rows:
            run_count = row['run_count'] or 1
            data.append({
                'template_id': row['job_template__id'],
                'template_name': row['job_template__name'],
                'run_count': row['run_count'],
                'avg_duration': round(float(row['avg_duration'] or 0), 1),
                'success_rate': round(row['successful'] / run_count * 100, 1),
            })

        return Response(data)


# ---------------------------------------------------------------------------
# Busiest Hosts
# ---------------------------------------------------------------------------

class BusiestHostsView(APIView):
    """Hosts with most automation activity."""
    permission_classes = [IsAuthenticated]

    def get(self, request, format=None):
        start, end = _get_date_range(request)
        limit = int(request.query_params.get('limit', 10))

        summaries = models.JobHostSummary.objects.filter(
            job__finished__range=(start, end),
        )

        rows = (
            summaries
            .values('host_name')
            .annotate(
                job_count=Count('job', distinct=True),
                total_ok=Sum('ok'),
                total_changed=Sum('changed'),
                total_failures=Sum('failures'),
                total_skipped=Sum('skipped'),
            )
            .order_by('-job_count')[:limit]
        )

        return Response(list(rows))


# ---------------------------------------------------------------------------
# Host Coverage
# ---------------------------------------------------------------------------

class HostCoverageView(APIView):
    """Automation coverage across inventories."""
    permission_classes = [IsAuthenticated]

    def get(self, request, format=None):
        user_hosts = get_user_queryset(request.user, models.Host)
        total = user_hosts.count()
        automated = user_hosts.filter(last_job__isnull=False).count()

        by_inventory = []
        inv_rows = (
            user_hosts
            .values('inventory__id', 'inventory__name')
            .annotate(
                total=Count('id'),
                automated=Count('id', filter=Q(last_job__isnull=False)),
            )
            .order_by('-total')[:20]
        )

        for row in inv_rows:
            inv_total = row['total'] or 1
            by_inventory.append({
                'inventory_id': row['inventory__id'],
                'name': row['inventory__name'],
                'total': row['total'],
                'automated': row['automated'],
                'pct': round(row['automated'] / inv_total * 100, 1),
            })

        return Response({
            'total_hosts': total,
            'automated_hosts': automated,
            'coverage_pct': round(automated / max(total, 1) * 100, 1),
            'by_inventory': by_inventory,
        })


# ---------------------------------------------------------------------------
# Failure Analysis
# ---------------------------------------------------------------------------

class FailureAnalysisView(APIView):
    """Breakdown of failures by template and host."""
    permission_classes = [IsAuthenticated]

    def get(self, request, format=None):
        start, end = _get_date_range(request)
        limit = int(request.query_params.get('limit', 10))

        failed_jobs = get_user_queryset(request.user, models.Job).filter(
            finished__range=(start, end),
            status='failed',
            job_template__isnull=False,
        )

        by_template = list(
            failed_jobs
            .values('job_template__name')
            .annotate(failure_count=Count('id'))
            .order_by('-failure_count')[:limit]
        )

        by_host = list(
            models.JobHostSummary.objects.filter(
                job__finished__range=(start, end),
                failed=True,
            )
            .values('host_name')
            .annotate(failure_count=Count('id'))
            .order_by('-failure_count')[:limit]
        )

        return Response({
            'by_template': [{'template_name': r['job_template__name'], 'failure_count': r['failure_count']} for r in by_template],
            'by_host': [{'host_name': r['host_name'], 'failure_count': r['failure_count']} for r in by_host],
        })


# ---------------------------------------------------------------------------
# Time Savings Calculator
# ---------------------------------------------------------------------------

class TimeSavingsView(APIView):
    """Estimate time saved through automation."""
    permission_classes = [IsAuthenticated]

    def get(self, request, format=None):
        start, end = _get_date_range(request)
        manual_multiplier = float(request.query_params.get('manual_multiplier', 10))

        jobs = get_user_queryset(request.user, models.Job).filter(
            finished__range=(start, end),
            status='successful',
        )

        agg = jobs.aggregate(
            total_elapsed=Sum('elapsed'),
            job_count=Count('id'),
            avg_duration=Avg('elapsed'),
        )

        total_seconds = float(agg['total_elapsed'] or 0)
        estimated_manual = total_seconds * manual_multiplier
        time_saved = estimated_manual - total_seconds

        return Response({
            'total_automated_seconds': round(total_seconds, 1),
            'estimated_manual_seconds': round(estimated_manual, 1),
            'time_saved_seconds': round(time_saved, 1),
            'time_saved_hours': round(time_saved / 3600, 1),
            'job_count': agg['job_count'] or 0,
            'avg_job_duration': round(float(agg['avg_duration'] or 0), 1),
            'manual_multiplier': manual_multiplier,
        })
