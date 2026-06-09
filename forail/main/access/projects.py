# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q

from rest_framework.exceptions import PermissionDenied

from forail.main.access.base import (
    BaseAccess,
    NotificationAttachMixin,
    check_superuser,
    get_object_from_data,
)
from forail.main.models import (
    Credential,
    ExecutionEnvironment,
    Organization,
    Project,
    ProjectUpdate,
)


class ExecutionEnvironmentAccess(BaseAccess):
    """
    I can see an execution environment when:
     - I can see its organization
     - It is a global ExecutionEnvironment
    I can create/change an execution environment when:
     - I'm a superuser
     - I have an organization or object role that gives access
    """

    model = ExecutionEnvironment
    select_related = ('organization',)
    prefetch_related = ('organization__admin_role', 'organization__execution_environment_admin_role')

    def filtered_queryset(self):
        return ExecutionEnvironment.objects.filter(
            Q(organization__in=Organization.accessible_pk_qs(self.user, 'read_role')) | Q(organization__isnull=True)
        ).distinct()

    @check_superuser
    def can_add(self, data):
        if not data:  # So the browseable API will work
            return Organization.accessible_objects(self.user, 'execution_environment_admin_role').exists()
        return self.check_related('organization', Organization, data, mandatory=True, role_field='execution_environment_admin_role')

    @check_superuser
    def can_change(self, obj, data):
        if obj and obj.organization_id is None:
            raise PermissionDenied
        if settings.ANSIBLE_BASE_ROLE_SYSTEM_ACTIVATED:
            if not self.user.has_obj_perm(obj, 'change'):
                return False
        else:
            if self.user not in obj.organization.execution_environment_admin_role:
                raise PermissionDenied
        if data and 'organization' in data:
            new_org = get_object_from_data('organization', Organization, data, obj=obj)
            if not new_org or self.user not in new_org.execution_environment_admin_role:
                return False
        return self.check_related('organization', Organization, data, obj=obj, role_field='execution_environment_admin_role')

    def can_delete(self, obj):
        if obj.managed:
            raise PermissionDenied
        return self.can_change(obj, None)


class ProjectAccess(NotificationAttachMixin, BaseAccess):
    """
    I can see projects when:
     - I am a superuser.
     - I am an admin in an organization associated with the project.
     - I am a project admin in an organization associated with the project.
     - I am a user in an organization associated with the project.
     - I am on a team associated with the project.
     - I have been explicitly granted permission to run/check jobs using the
       project.
     - I created the project but it isn't associated with an organization
    I can change/delete when:
     - I am a superuser.
     - I am an admin in an organization associated with the project.
     - I created the project but it isn't associated with an organization
    """

    model = Project
    select_related = ('credential',)
    prefetch_related = ('modified_by', 'created_by', 'organization', 'last_job', 'current_job')
    notification_attach_roles = ['admin_role']

    def filtered_queryset(self):
        return self.model.accessible_objects(self.user, 'read_role')

    @check_superuser
    def can_add(self, data):
        if not data:  # So the browseable API will work
            return Organization.accessible_objects(self.user, 'project_admin_role').exists()

        if data.get('default_environment'):
            ee = get_object_from_data('default_environment', ExecutionEnvironment, data)
            if not self.user.can_access(ExecutionEnvironment, 'read', ee):
                return False

        return self.check_related('organization', Organization, data, role_field='project_admin_role', mandatory=True) and self.check_related(
            'credential', Credential, data, role_field='use_role'
        )

    @check_superuser
    def can_change(self, obj, data):
        if data and data.get('default_environment'):
            ee = get_object_from_data('default_environment', ExecutionEnvironment, data, obj=obj)
            if not self.user.can_access(ExecutionEnvironment, 'read', ee):
                return False

        return (
            self.check_related('organization', Organization, data, obj=obj, role_field='project_admin_role')
            and self.user in obj.admin_role
            and self.check_related('credential', Credential, data, obj=obj, role_field='use_role')
        )

    @check_superuser
    def can_start(self, obj, validate_license=True):
        return obj and self.user in obj.update_role

    def can_delete(self, obj):
        return self.can_change(obj, None)


class ProjectUpdateAccess(BaseAccess):
    """
    I can see project updates when I can see the project.
    I can change when I can change the project.
    I can delete when I can change/delete the project.
    """

    model = ProjectUpdate
    select_related = (
        'created_by',
        'modified_by',
        'project',
    )
    prefetch_related = (
        'unified_job_template',
        'instance_group',
    )

    def filtered_queryset(self):
        return self.model.objects.filter(project__in=Project.accessible_pk_qs(self.user, 'read_role'))

    @check_superuser
    def can_cancel(self, obj):
        if self.user == obj.created_by:
            return True
        # Project updates cascade delete with project, admin role descends from org admin
        return self.user in obj.project.admin_role

    def can_start(self, obj, validate_license=True):
        # for relaunching
        try:
            if obj and obj.project:
                return self.user in obj.project.update_role
        except ObjectDoesNotExist:
            pass
        return False

    @check_superuser
    def can_delete(self, obj):
        return obj and self.user in obj.project.admin_role
