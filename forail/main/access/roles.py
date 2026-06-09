# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

import logging

from django.conf import settings
from django.contrib.auth.models import User

from forail.main.access.base import BaseAccess, check_superuser, check_user_access
from forail.main.models import Organization, Role, Team
from forail.main.models.mixins import ResourceMixin

logger = logging.getLogger('forail.main.access')


class RoleAccess(BaseAccess):
    """
    - I can see roles when
      - I am a super user
      - I am a member of that role
      - The role is a descdendent role of a role I am a member of
      - The role is an implicit role of an object that I can see a role of.
    """

    model = Role
    prefetch_related = ('content_type',)

    def filtered_queryset(self):
        result = Role.visible_roles(self.user)
        # Make system admin/auditor mandatorily visible.
        mandatories = ('system_administrator', 'system_auditor')
        super_qs = Role.objects.filter(singleton_name__in=mandatories)
        return result | super_qs

    def can_add(self, obj, data):
        # Unsupported for now
        return False

    def can_attach(self, obj, sub_obj, relationship, *args, **kwargs):
        return self.can_unattach(obj, sub_obj, relationship, *args, **kwargs)

    @check_superuser
    def can_unattach(self, obj, sub_obj, relationship, data=None, skip_sub_obj_read_check=False):
        if not skip_sub_obj_read_check and relationship in ['members', 'member_role.parents', 'parents']:
            # If we are unattaching a team Role, check the Team read access
            if relationship == 'parents':
                sub_obj_resource = sub_obj.content_object
            else:
                sub_obj_resource = sub_obj
            if not check_user_access(self.user, sub_obj_resource.__class__, 'read', sub_obj_resource):
                return False

        # Being a user in the member_role or admin_role of an organization grants
        # administrators of that Organization the ability to edit that user. To prevent
        # unwanted escalations let's ensure that the Organization administrator has the ability
        # to admin the user being added to the role.
        if isinstance(obj.content_object, Organization) and obj.role_field in ['admin_role', 'member_role']:
            if not isinstance(sub_obj, User):
                logger.error('Unexpected attempt to associate {} with organization role.'.format(sub_obj))
                return False
            if not settings.MANAGE_ORGANIZATION_AUTH and not self.user.is_superuser:
                return False
            from forail.main.access.users import UserAccess
            if not UserAccess(self.user).can_admin(sub_obj, None, allow_orphans=True):
                return False

        if isinstance(obj.content_object, Team) and obj.role_field in ['admin_role', 'member_role']:
            if not settings.MANAGE_ORGANIZATION_AUTH and not self.user.is_superuser:
                return False

        if isinstance(obj.content_object, ResourceMixin) and self.user in obj.content_object.admin_role:
            return True
        return False

    def can_delete(self, obj):
        # Unsupported for now
        return False
