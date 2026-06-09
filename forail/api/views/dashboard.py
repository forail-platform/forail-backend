# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

import dateutil
import itertools
import time

from collections import OrderedDict

from django.db.models import Sum, Count
from django.db.models.functions import Trunc
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _

from rest_framework.response import Response
from rest_framework import status

from forail.main.access import get_user_queryset
from forail.api.generics import APIView
from forail.api.versioning import reverse
from forail.main import models


class DashboardView(APIView):
    deprecated = True

    name = _("Dashboard")
    swagger_topic = 'Dashboard'

    def get(self, request, format=None):
        '''Show Dashboard Details'''
        data = OrderedDict()
        data['related'] = {'jobs_graph': reverse('api:dashboard_jobs_graph_view', request=request)}
        user_inventory = get_user_queryset(request.user, models.Inventory)
        inventory_with_failed_hosts = user_inventory.filter(hosts_with_active_failures__gt=0)
        user_inventory_external = user_inventory.filter(has_inventory_sources=True)
        # if there are *zero* inventories, this aggregate query will be None, fall back to 0
        failed_inventory = user_inventory.aggregate(Sum('inventory_sources_with_failures'))['inventory_sources_with_failures__sum'] or 0
        data['inventories'] = {
            'url': reverse('api:inventory_list', request=request),
            'total': user_inventory.count(),
            'total_with_inventory_source': user_inventory_external.count(),
            'job_failed': inventory_with_failed_hosts.count(),
            'inventory_failed': failed_inventory,
        }
        user_inventory_sources = get_user_queryset(request.user, models.InventorySource)
        ec2_inventory_sources = user_inventory_sources.filter(source='ec2')
        ec2_inventory_failed = ec2_inventory_sources.filter(status='failed')
        data['inventory_sources'] = {}
        data['inventory_sources']['ec2'] = {
            'url': reverse('api:inventory_source_list', request=request) + "?source=ec2",
            'failures_url': reverse('api:inventory_source_list', request=request) + "?source=ec2&status=failed",
            'label': 'Amazon EC2',
            'total': ec2_inventory_sources.count(),
            'failed': ec2_inventory_failed.count(),
        }

        user_groups = get_user_queryset(request.user, models.Group)
        groups_inventory_failed = models.Group.objects.filter(inventory_sources__last_job_failed=True).count()
        data['groups'] = {'url': reverse('api:group_list', request=request), 'total': user_groups.count(), 'inventory_failed': groups_inventory_failed}

        user_hosts = get_user_queryset(request.user, models.Host)
        user_hosts_failed = user_hosts.filter(last_job_host_summary__failed=True)
        data['hosts'] = {
            'url': reverse('api:host_list', request=request),
            'failures_url': reverse('api:host_list', request=request) + "?last_job_host_summary__failed=True",
            'total': user_hosts.count(),
            'failed': user_hosts_failed.count(),
        }

        user_projects = get_user_queryset(request.user, models.Project)
        user_projects_failed = user_projects.filter(last_job_failed=True)
        data['projects'] = {
            'url': reverse('api:project_list', request=request),
            'failures_url': reverse('api:project_list', request=request) + "?last_job_failed=True",
            'total': user_projects.count(),
            'failed': user_projects_failed.count(),
        }

        git_projects = user_projects.filter(scm_type='git')
        git_failed_projects = git_projects.filter(last_job_failed=True)
        svn_projects = user_projects.filter(scm_type='svn')
        svn_failed_projects = svn_projects.filter(last_job_failed=True)
        archive_projects = user_projects.filter(scm_type='archive')
        archive_failed_projects = archive_projects.filter(last_job_failed=True)
        data['scm_types'] = {}
        data['scm_types']['git'] = {
            'url': reverse('api:project_list', request=request) + "?scm_type=git",
            'label': 'Git',
            'failures_url': reverse('api:project_list', request=request) + "?scm_type=git&last_job_failed=True",
            'total': git_projects.count(),
            'failed': git_failed_projects.count(),
        }
        data['scm_types']['svn'] = {
            'url': reverse('api:project_list', request=request) + "?scm_type=svn",
            'label': 'Subversion',
            'failures_url': reverse('api:project_list', request=request) + "?scm_type=svn&last_job_failed=True",
            'total': svn_projects.count(),
            'failed': svn_failed_projects.count(),
        }
        data['scm_types']['archive'] = {
            'url': reverse('api:project_list', request=request) + "?scm_type=archive",
            'label': 'Remote Archive',
            'failures_url': reverse('api:project_list', request=request) + "?scm_type=archive&last_job_failed=True",
            'total': archive_projects.count(),
            'failed': archive_failed_projects.count(),
        }

        user_list = get_user_queryset(request.user, models.User)
        team_list = get_user_queryset(request.user, models.Team)
        credential_list = get_user_queryset(request.user, models.Credential)
        job_template_list = get_user_queryset(request.user, models.JobTemplate)
        organization_list = get_user_queryset(request.user, models.Organization)
        data['users'] = {'url': reverse('api:user_list', request=request), 'total': user_list.count()}
        data['organizations'] = {'url': reverse('api:organization_list', request=request), 'total': organization_list.count()}
        data['teams'] = {'url': reverse('api:team_list', request=request), 'total': team_list.count()}
        data['credentials'] = {'url': reverse('api:credential_list', request=request), 'total': credential_list.count()}
        data['job_templates'] = {'url': reverse('api:job_template_list', request=request), 'total': job_template_list.count()}
        return Response(data)


class DashboardJobsGraphView(APIView):
    name = _("Dashboard Jobs Graphs")
    swagger_topic = 'Jobs'

    def get(self, request, format=None):
        period = request.query_params.get('period', 'month')
        job_type = request.query_params.get('job_type', 'all')

        user_unified_jobs = get_user_queryset(request.user, models.UnifiedJob).exclude(launch_type='sync')

        success_query = user_unified_jobs.filter(status='successful')
        failed_query = user_unified_jobs.filter(status='failed')
        canceled_query = user_unified_jobs.filter(status='canceled')
        error_query = user_unified_jobs.filter(status='error')

        if job_type == 'inv_sync':
            success_query = success_query.filter(instance_of=models.InventoryUpdate)
            failed_query = failed_query.filter(instance_of=models.InventoryUpdate)
            canceled_query = canceled_query.filter(instance_of=models.InventoryUpdate)
            error_query = error_query.filter(instance_of=models.InventoryUpdate)
        elif job_type == 'playbook_run':
            success_query = success_query.filter(instance_of=models.Job)
            failed_query = failed_query.filter(instance_of=models.Job)
            canceled_query = canceled_query.filter(instance_of=models.Job)
            error_query = error_query.filter(instance_of=models.Job)
        elif job_type == 'scm_update':
            success_query = success_query.filter(instance_of=models.ProjectUpdate)
            failed_query = failed_query.filter(instance_of=models.ProjectUpdate)
            canceled_query = canceled_query.filter(instance_of=models.ProjectUpdate)
            error_query = error_query.filter(instance_of=models.ProjectUpdate)

        end = now()
        interval = 'day'
        if period == 'month':
            start = end - dateutil.relativedelta.relativedelta(months=1)
        elif period == 'two_weeks':
            start = end - dateutil.relativedelta.relativedelta(weeks=2)
        elif period == 'week':
            start = end - dateutil.relativedelta.relativedelta(weeks=1)
        elif period == 'day':
            start = end - dateutil.relativedelta.relativedelta(days=1)
            interval = 'hour'
        else:
            return Response({'error': _('Unknown period "%s"') % str(period)}, status=status.HTTP_400_BAD_REQUEST)

        dashboard_data = {"jobs": {"successful": [], "failed": [], "canceled": [], "error": []}}

        succ_list = dashboard_data['jobs']['successful']
        fail_list = dashboard_data['jobs']['failed']
        canceled_list = dashboard_data['jobs']['canceled']
        error_list = dashboard_data['jobs']['error']

        qs_s = (
            success_query.filter(finished__range=(start, end))
            .annotate(d=Trunc('finished', interval, tzinfo=end.tzinfo))
            .order_by()
            .values('d')
            .annotate(agg=Count('id', distinct=True))
        )
        data_s = {item['d']: item['agg'] for item in qs_s}
        qs_f = (
            failed_query.filter(finished__range=(start, end))
            .annotate(d=Trunc('finished', interval, tzinfo=end.tzinfo))
            .order_by()
            .values('d')
            .annotate(agg=Count('id', distinct=True))
        )
        data_f = {item['d']: item['agg'] for item in qs_f}
        qs_c = (
            canceled_query.filter(finished__range=(start, end))
            .annotate(d=Trunc('finished', interval, tzinfo=end.tzinfo))
            .order_by()
            .values('d')
            .annotate(agg=Count('id', distinct=True))
        )
        data_c = {item['d']: item['agg'] for item in qs_c}
        qs_e = (
            error_query.filter(finished__range=(start, end))
            .annotate(d=Trunc('finished', interval, tzinfo=end.tzinfo))
            .order_by()
            .values('d')
            .annotate(agg=Count('id', distinct=True))
        )
        data_e = {item['d']: item['agg'] for item in qs_e}

        start_date = start.replace(hour=0, minute=0, second=0, microsecond=0)
        for d in itertools.count():
            date = start_date + dateutil.relativedelta.relativedelta(days=d)
            if date > end:
                break
            succ_list.append([time.mktime(date.timetuple()), data_s.get(date, 0)])
            fail_list.append([time.mktime(date.timetuple()), data_f.get(date, 0)])
            canceled_list.append([time.mktime(date.timetuple()), data_c.get(date, 0)])
            error_list.append([time.mktime(date.timetuple()), data_e.get(date, 0)])

        return Response(dashboard_data)
