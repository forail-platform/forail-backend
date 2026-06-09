# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

from django.conf import settings
from django.db.models import Q

from forail.main.access.base import BaseAccess, check_superuser
from forail.main.models import (
    Label,
    Notification,
    NotificationTemplate,
    Organization,
    UnifiedJobTemplate,
)


class NotificationTemplateAccess(BaseAccess):
    """
    Run standard logic from DAB RBAC
    """

    model = NotificationTemplate
    prefetch_related = ('created_by', 'modified_by', 'organization')

    def filtered_queryset(self):
        if settings.ANSIBLE_BASE_ROLE_SYSTEM_ACTIVATED:
            return self.model.access_qs(self.user, 'view')
        return self.model.objects.filter(
            Q(organization__in=Organization.accessible_objects(self.user, 'notification_admin_role')) | Q(organization__in=self.user.auditor_of_organizations)
        ).distinct()

    @check_superuser
    def can_add(self, data):
        if not data:
            return Organization.accessible_objects(self.user, 'notification_admin_role').exists()
        return self.check_related('organization', Organization, data, role_field='notification_admin_role', mandatory=True)

    @check_superuser
    def can_change(self, obj, data):
        return self.user.has_obj_perm(obj, 'change') and self.check_related('organization', Organization, data, obj=obj, role_field='notification_admin_role')

    def can_admin(self, obj, data):
        return self.can_change(obj, data)

    def can_delete(self, obj):
        return self.can_change(obj, None)

    @check_superuser
    def can_start(self, obj, validate_license=True):
        return self.can_change(obj, None)


class NotificationAccess(BaseAccess):
    """
    I can see/use a notification if I have permission to
    """

    model = Notification
    prefetch_related = ('notification_template',)

    def filtered_queryset(self):
        return self.model.objects.filter(
            Q(notification_template__organization__in=Organization.accessible_objects(self.user, 'notification_admin_role'))
            | Q(notification_template__organization__in=self.user.auditor_of_organizations)
        ).distinct()

    def can_delete(self, obj):
        return self.user.can_access(NotificationTemplate, 'delete', obj.notification_template)


class LabelAccess(BaseAccess):
    """
    I can see/use a Label if I have permission to associated organization, or to a JT that the label is on
    """

    model = Label
    prefetch_related = (
        'modified_by',
        'created_by',
        'organization',
    )

    def filtered_queryset(self):
        return self.model.objects.filter(
            Q(organization__in=Organization.accessible_pk_qs(self.user, 'read_role'))
            | Q(unifiedjobtemplate_labels__in=UnifiedJobTemplate.accessible_pk_qs(self.user, 'read_role'))
        ).distinct()

    @check_superuser
    def can_add(self, data):
        if not data:  # So the browseable API will work
            return True
        return self.check_related('organization', Organization, data, role_field='member_role', mandatory=True)

    @check_superuser
    def can_change(self, obj, data):
        if self.can_add(data) is False:
            return False

        return self.user in obj.organization.admin_role

    def can_delete(self, obj):
        return self.can_change(obj, None)
