# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

from django.conf import settings

from forail.main.access.base import BaseAccess, UnifiedCredentialsMixin, check_superuser
from forail.main.access.jobs import JobLaunchConfigAccess
from forail.main.access.unified import UnifiedJobTemplateAccess
from forail.main.models import (
    Role,
    Schedule,
    UnifiedJobTemplate,
)


class ScheduleAccess(UnifiedCredentialsMixin, BaseAccess):
    """
    I can see a schedule if I can see it's related unified job, I can create them or update them if I have write access
    """

    model = Schedule
    select_related = (
        'created_by',
        'modified_by',
    )
    prefetch_related = (
        'unified_job_template',
        'credentials',
    )

    def filtered_queryset(self):
        return self.model.objects.filter(unified_job_template__in=UnifiedJobTemplateAccess(self.user).filtered_queryset())

    @check_superuser
    def can_add(self, data):
        if not JobLaunchConfigAccess(self.user).can_add(data):
            return False
        if not data:
            if settings.ANSIBLE_BASE_ROLE_SYSTEM_ACTIVATED:
                return self.user.has_roles.filter(permission_partials__codename__in=['execute_jobtemplate', 'update_project', 'update_inventory']).exists()
            return Role.objects.filter(role_field__in=['update_role', 'execute_role'], ancestors__in=self.user.roles.all()).exists()

        return self.check_related('unified_job_template', UnifiedJobTemplate, data, role_field='execute_role', mandatory=True)

    @check_superuser
    def can_change(self, obj, data):
        if not JobLaunchConfigAccess(self.user).can_change(obj, data):
            return False
        if self.check_related('unified_job_template', UnifiedJobTemplate, data, obj=obj, mandatory=True):
            return True
        # Users with execute role can modify the schedules they created
        return obj.created_by == self.user and self.check_related(
            'unified_job_template', UnifiedJobTemplate, data, obj=obj, role_field='execute_role', mandatory=True
        )

    def can_delete(self, obj):
        return self.can_change(obj, {})
