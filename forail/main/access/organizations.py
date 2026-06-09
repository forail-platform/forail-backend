# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

import logging

from django.conf import settings
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from rest_framework.exceptions import PermissionDenied

from forail.main.access.base import (
    BaseAccess,
    NotificationAttachMixin,
    check_superuser,
    get_object_from_data,
    get_pk_from_dict,
)
from forail.main.models import (
    ExecutionEnvironment,
    Organization,
    Role,
    Team,
)
from forail.main.models.mixins import ResourceMixin

logger = logging.getLogger('forail.main.access')


class OrganizationAccess(NotificationAttachMixin, BaseAccess):
    """
    I can see organizations when:
     - I am a superuser.
     - I am an admin or user in that organization.
    I can change or delete organizations when:
     - I am a superuser.
     - I'm an admin of that organization.
    I can associate/disassociate instance groups when:
     - I am a superuser.
    """

    model = Organization
    prefetch_related = (
        'created_by',
        'modified_by',
        'resource',  # dab_resource_registry
    )
    # organization admin_role is not a parent of organization auditor_role
    notification_attach_roles = ['admin_role', 'auditor_role']

    def filtered_queryset(self):
        return self.model.accessible_objects(self.user, 'read_role')

    @check_superuser
    def can_change(self, obj, data):
        if data and data.get('default_environment'):
            ee = get_object_from_data('default_environment', ExecutionEnvironment, data)
            if not self.user.can_access(ExecutionEnvironment, 'read', ee):
                return False

        return self.user in obj.admin_role

    def can_delete(self, obj):
        is_change_possible = self.can_change(obj, None)
        if not is_change_possible:
            return False
        return True

    def can_attach(self, obj, sub_obj, relationship, *args, **kwargs):
        # If the request is updating the membership, check the membership role permissions instead
        if relationship in ('member_role.members', 'admin_role.members'):
            from forail.main.access.roles import RoleAccess
            rel_role = getattr(obj, relationship.split('.')[0])
            return RoleAccess(self.user).can_attach(rel_role, sub_obj, 'members', *args, **kwargs)

        if relationship == "instance_groups":
            if self.user in obj.admin_role and self.user in sub_obj.use_role:
                return True
            return False
        return super(OrganizationAccess, self).can_attach(obj, sub_obj, relationship, *args, **kwargs)

    def can_unattach(self, obj, sub_obj, relationship, *args, **kwargs):
        # If the request is updating the membership, check the membership role permissions instead
        if relationship in ('member_role.members', 'admin_role.members'):
            from forail.main.access.roles import RoleAccess
            rel_role = getattr(obj, relationship.split('.')[0])
            return RoleAccess(self.user).can_unattach(rel_role, sub_obj, 'members', *args, **kwargs)

        if relationship == "instance_groups":
            return self.can_attach(obj, sub_obj, relationship, *args, **kwargs)
        return super(OrganizationAccess, self).can_attach(obj, sub_obj, relationship, *args, **kwargs)


class TeamAccess(BaseAccess):
    """
    I can see a team when:
     - I'm a superuser.
     - I'm an admin of the team
     - I'm a member of that team.
     - I'm a member of the team's organization
    I can create/change a team when:
     - I'm a superuser.
     - I'm an admin for the team
    """

    model = Team
    select_related = (
        'created_by',
        'modified_by',
        'organization',
        'resource',  # dab_resource_registry
    )

    def filtered_queryset(self):
        if settings.ORG_ADMINS_CAN_SEE_ALL_USERS and (self.user.admin_of_organizations.exists() or self.user.auditor_of_organizations.exists()):
            return self.model.objects.all()
        return self.model.objects.filter(
            Q(organization__in=Organization.accessible_pk_qs(self.user, 'member_role')) | Q(pk__in=self.model.accessible_pk_qs(self.user, 'read_role'))
        )

    @check_superuser
    def can_add(self, data):
        if not data:  # So the browseable API will work
            return Organization.accessible_objects(self.user, 'admin_role').exists()
        if not settings.MANAGE_ORGANIZATION_AUTH:
            return False
        return self.check_related('organization', Organization, data)

    def can_change(self, obj, data):
        # Prevent moving a team to a different organization.
        org_pk = get_pk_from_dict(data, 'organization')
        if obj and org_pk and obj.organization.pk != org_pk:
            raise PermissionDenied(_('Unable to change organization on a team.'))
        if self.user.is_superuser:
            return True
        if not settings.MANAGE_ORGANIZATION_AUTH:
            return False
        return self.user in obj.admin_role

    def can_delete(self, obj):
        return self.can_change(obj, None)

    def can_attach(self, obj, sub_obj, relationship, *args, **kwargs):
        """Reverse obj and sub_obj, defer to RoleAccess if this is an assignment
        of a resource role to the team."""
        # MANAGE_ORGANIZATION_AUTH setting checked in RoleAccess
        if isinstance(sub_obj, Role):
            if sub_obj.content_object is None:
                raise PermissionDenied(_("The {} role cannot be assigned to a team").format(sub_obj.name))

            if isinstance(sub_obj.content_object, ResourceMixin):
                from forail.main.access.roles import RoleAccess
                role_access = RoleAccess(self.user)
                return role_access.can_attach(sub_obj, obj, 'member_role.parents', *args, **kwargs)
        if self.user.is_superuser:
            return True

        # If the request is updating the membership, check the membership role permissions instead
        if relationship in ('member_role.members', 'admin_role.members'):
            from forail.main.access.roles import RoleAccess
            rel_role = getattr(obj, relationship.split('.')[0])
            return RoleAccess(self.user).can_attach(rel_role, sub_obj, 'members', *args, **kwargs)

        return super(TeamAccess, self).can_attach(obj, sub_obj, relationship, *args, **kwargs)

    def can_unattach(self, obj, sub_obj, relationship, *args, **kwargs):
        # MANAGE_ORGANIZATION_AUTH setting checked in RoleAccess
        if isinstance(sub_obj, Role):
            if isinstance(sub_obj.content_object, ResourceMixin):
                from forail.main.access.roles import RoleAccess
                role_access = RoleAccess(self.user)
                return role_access.can_unattach(sub_obj, obj, 'member_role.parents', *args, **kwargs)

        # If the request is updating the membership, check the membership role permissions instead
        if relationship in ('member_role.members', 'admin_role.members'):
            from forail.main.access.roles import RoleAccess
            rel_role = getattr(obj, relationship.split('.')[0])
            return RoleAccess(self.user).can_unattach(rel_role, sub_obj, 'members', *args, **kwargs)

        return super(TeamAccess, self).can_unattach(obj, sub_obj, relationship, *args, **kwargs)
