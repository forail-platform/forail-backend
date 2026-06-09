# Copyright (c) 2015 Ansible, Inc.
# Copyright (c) 2026 Krstan Vjestica / Forail Project
# All Rights Reserved.

"""Event serializers for the Forail API."""

import json
import logging

from django.conf import settings

from rest_framework import serializers

from forail.main.models import (
    AdHocCommandEvent,
    InventoryUpdateEvent,
    JobEvent,
    ProjectUpdateEvent,
    SystemJobEvent,
)
from forail.main.utils import truncate_stdout
from forail.main.redact import UriCleaner
from forail.api.serializers.base import BaseSerializer

logger = logging.getLogger('forail.api.serializers')


class JobEventSerializer(BaseSerializer):
    event_display = serializers.CharField(source='get_event_display2', read_only=True)
    event_level = serializers.IntegerField(read_only=True)

    class Meta:
        model = JobEvent
        fields = (
            '*',
            '-name',
            '-description',
            'job',
            'event',
            'counter',
            'event_display',
            'event_data',
            'event_level',
            'failed',
            'changed',
            'uuid',
            'parent_uuid',
            'host',
            'host_name',
            'playbook',
            'play',
            'task',
            'role',
            'stdout',
            'start_line',
            'end_line',
            'verbosity',
        )

    def get_related(self, obj):
        res = super(JobEventSerializer, self).get_related(obj)
        res.update(dict(job=self.reverse('api:job_detail', kwargs={'pk': obj.job_id})))
        res['children'] = self.reverse('api:job_event_children_list', kwargs={'pk': obj.pk})
        if obj.host_id:
            res['host'] = self.reverse('api:host_detail', kwargs={'pk': obj.host_id})
        return res

    def get_summary_fields(self, obj):
        d = super(JobEventSerializer, self).get_summary_fields(obj)
        try:
            d['job']['job_template_id'] = obj.job.job_template.id
            d['job']['job_template_name'] = obj.job.job_template.name
        except (KeyError, AttributeError):
            pass
        return d

    def to_representation(self, obj):
        data = super(JobEventSerializer, self).to_representation(obj)
        # Show full stdout for playbook_on_* events.
        if obj and obj.event.startswith('playbook_on'):
            return data
        # If the view logic says to not truncate (request was to the detail view or a param was used)
        if self.context.get('no_truncate', False):
            return data
        max_bytes = settings.EVENT_STDOUT_MAX_BYTES_DISPLAY
        if 'stdout' in data:
            data['stdout'] = truncate_stdout(data['stdout'], max_bytes)
        return data


class ProjectUpdateEventSerializer(JobEventSerializer):
    stdout = serializers.SerializerMethodField()
    event_data = serializers.SerializerMethodField()

    class Meta:
        model = ProjectUpdateEvent
        fields = ('*', '-name', '-description', '-job', '-job_id', '-parent_uuid', '-parent', '-host', 'project_update')

    def get_related(self, obj):
        res = super(JobEventSerializer, self).get_related(obj)
        res['project_update'] = self.reverse('api:project_update_detail', kwargs={'pk': obj.project_update_id})
        return res

    def get_stdout(self, obj):
        return UriCleaner.remove_sensitive(obj.stdout)

    def get_event_data(self, obj):
        # the project update playbook uses the git or svn modules
        # to clone repositories, and those modules are prone to printing
        # raw SCM URLs in their stdout (which *could* contain passwords)
        # attempt to detect and filter HTTP basic auth passwords in the stdout
        # of these types of events
        if obj.event_data.get('task_action') in ('git', 'svn', 'ansible.builtin.git', 'ansible.builtin.svn'):
            try:
                return json.loads(UriCleaner.remove_sensitive(json.dumps(obj.event_data)))
            except Exception:
                logger.exception("Failed to sanitize event_data")
                return {}
        else:
            return obj.event_data


class AdHocCommandEventSerializer(BaseSerializer):
    event_display = serializers.CharField(source='get_event_display', read_only=True)

    class Meta:
        model = AdHocCommandEvent
        fields = (
            '*',
            '-name',
            '-description',
            'ad_hoc_command',
            'event',
            'counter',
            'event_display',
            'event_data',
            'failed',
            'changed',
            'uuid',
            'host',
            'host_name',
            'stdout',
            'start_line',
            'end_line',
            'verbosity',
        )

    def get_related(self, obj):
        res = super(AdHocCommandEventSerializer, self).get_related(obj)
        res.update(dict(ad_hoc_command=self.reverse('api:ad_hoc_command_detail', kwargs={'pk': obj.ad_hoc_command_id})))
        if obj.host:
            res['host'] = self.reverse('api:host_detail', kwargs={'pk': obj.host.pk})
        return res

    def to_representation(self, obj):
        data = super(AdHocCommandEventSerializer, self).to_representation(obj)
        # If the view logic says to not truncate (request was to the detail view or a param was used)
        if self.context.get('no_truncate', False):
            return data
        max_bytes = settings.EVENT_STDOUT_MAX_BYTES_DISPLAY
        if 'stdout' in data:
            data['stdout'] = truncate_stdout(data['stdout'], max_bytes)
        return data


class InventoryUpdateEventSerializer(AdHocCommandEventSerializer):
    class Meta:
        model = InventoryUpdateEvent
        fields = ('*', '-name', '-description', '-ad_hoc_command', '-host', '-host_name', 'inventory_update')

    def get_related(self, obj):
        res = super(AdHocCommandEventSerializer, self).get_related(obj)
        res['inventory_update'] = self.reverse('api:inventory_update_detail', kwargs={'pk': obj.inventory_update_id})
        return res


class SystemJobEventSerializer(AdHocCommandEventSerializer):
    class Meta:
        model = SystemJobEvent
        fields = ('*', '-name', '-description', '-ad_hoc_command', '-host', '-host_name', 'system_job')

    def get_related(self, obj):
        res = super(AdHocCommandEventSerializer, self).get_related(obj)
        res['system_job'] = self.reverse('api:system_job_detail', kwargs={'pk': obj.system_job_id})
        return res
