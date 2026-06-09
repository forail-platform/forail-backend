# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

import logging

from django.conf import settings
from django.contrib.auth.models import User

from ansible_base.lib.utils.validation import to_python_boolean
from ansible_base.rbac.models import RoleEvaluation

from forail.main.access.base import BaseAccess, check_superuser, get_object_from_data
from forail.main.models import Organization
from forail.main.models.oauth import OAuth2Application, OAuth2AccessToken

logger = logging.getLogger('forail.main.access')


class UserAccess(BaseAccess):
    """
    I can see user records when:
     - I'm a superuser
     - I'm in a role with them (such as in an organization or team)
     - They are in a role which includes a role of mine
     - I am in a role that includes a role of theirs
    I can change some fields for a user (mainly password) when I am that user.
    I can change all fields for a user (admin access) or delete when:
     - I'm a superuser.
     - I'm their org admin.
    """

    model = User
    prefetch_related = (
        'profile',
        'resource',
    )

    def filtered_queryset(self):
        if settings.ORG_ADMINS_CAN_SEE_ALL_USERS and (self.user.admin_of_organizations.exists() or self.user.auditor_of_organizations.exists()):
            qs = User.objects.all()
        else:
            qs = (
                User.objects.filter(pk__in=Organization.accessible_objects(self.user, 'read_role').values('member_role__members'))
                | User.objects.filter(pk=self.user.id)
                | User.objects.filter(is_superuser=True)
            ).distinct()
        return qs

    def can_add(self, data):
        if data is not None and ('is_superuser' in data or 'is_system_auditor' in data):
            if (
                to_python_boolean(data.get('is_superuser', 'false'), allow_none=True)
                or to_python_boolean(data.get('is_system_auditor', 'false'), allow_none=True)
            ) and not self.user.is_superuser:
                return False
        if self.user.is_superuser:
            return True
        if not settings.MANAGE_ORGANIZATION_AUTH:
            return False
        return Organization.accessible_objects(self.user, 'admin_role').exists()

    def can_change(self, obj, data):
        if data is not None and ('is_superuser' in data or 'is_system_auditor' in data):
            if to_python_boolean(data.get('is_superuser', 'false'), allow_none=True) and not self.user.is_superuser:
                return False
            if to_python_boolean(data.get('is_system_auditor', 'false'), allow_none=True) and not (self.user.is_superuser or self.user == obj):
                return False
        # A user can be changed if they are themselves, or by org admins or
        # superusers.  Change permission implies changing only certain fields
        # that a user should be able to edit for themselves.
        if not settings.MANAGE_ORGANIZATION_AUTH and not self.user.is_superuser:
            return False
        return bool(self.user == obj or self.can_admin(obj, data))

    @staticmethod
    def user_organizations(u):
        """
        Returns all organizations that count `u` as a member
        """
        return Organization.accessible_objects(u, 'member_role')

    def is_all_org_admin(self, u):
        """
        returns True if `u` is member of any organization that is
        not also an organization that `self.user` admins
        """
        return not self.user_organizations(u).exclude(pk__in=Organization.accessible_pk_qs(self.user, 'admin_role')).exists()

    def user_is_orphaned(self, u):
        return not self.user_organizations(u).exists()

    @check_superuser
    def can_admin(self, obj, data, allow_orphans=False, check_setting=True):
        if check_setting and (not settings.MANAGE_ORGANIZATION_AUTH):
            return False
        if obj.is_superuser or obj.is_system_auditor:
            # must be superuser to admin users with system roles
            return False
        if self.user_is_orphaned(obj):
            if not allow_orphans:
                # in these cases only superusers can modify orphan users
                return False
            if settings.ANSIBLE_BASE_ROLE_SYSTEM_ACTIVATED:
                # Permission granted if the user has all permissions that the target user has
                target_perms = set(
                    RoleEvaluation.objects.filter(role__in=obj.has_roles.all()).values_list('object_id', 'content_type_id', 'codename').distinct()
                )
                user_perms = set(
                    RoleEvaluation.objects.filter(role__in=self.user.has_roles.all()).values_list('object_id', 'content_type_id', 'codename').distinct()
                )
                return not (target_perms - user_perms)
            return not obj.roles.all().exclude(ancestors__in=self.user.roles.all()).exists()
        else:
            return self.is_all_org_admin(obj)

    def can_delete(self, obj):
        if obj == self.user:
            # cannot delete yourself
            return False
        super_users = User.objects.filter(is_superuser=True)
        if obj.is_superuser and super_users.count() == 1:
            # cannot delete the last active superuser
            return False
        if self.can_admin(obj, None, allow_orphans=True):
            return True
        return False

    def can_attach(self, obj, sub_obj, relationship, *args, **kwargs):
        # The only thing that a User should ever have attached is a Role
        if relationship == 'roles':
            from forail.main.access.roles import RoleAccess
            role_access = RoleAccess(self.user)
            return role_access.can_attach(sub_obj, obj, 'members', *args, **kwargs)

        logger.error('Unexpected attempt to associate {} with a user.'.format(sub_obj))
        return False

    def can_unattach(self, obj, sub_obj, relationship, *args, **kwargs):
        # The only thing that a User should ever have to be unattached is a Role
        if relationship == 'roles':
            from forail.main.access.roles import RoleAccess
            role_access = RoleAccess(self.user)
            return role_access.can_unattach(sub_obj, obj, 'members', *args, **kwargs)

        logger.error('Unexpected attempt to de-associate {} from a user.'.format(sub_obj))
        return False


class OAuth2ApplicationAccess(BaseAccess):
    """
    I can read, change or delete OAuth 2 applications when:
     - I am a superuser.
     - I am the admin of the organization of the user of the application.
     - I am a user in the organization of the application.
    I can create OAuth 2 applications when:
     - I am a superuser.
     - I am the admin of the organization of the application.
    """

    model = OAuth2Application
    select_related = ('user',)
    prefetch_related = ('organization', 'oauth2accesstoken_set')

    def filtered_queryset(self):
        org_access_qs = Organization.accessible_objects(self.user, 'member_role')
        return self.model.objects.filter(organization__in=org_access_qs)

    def can_change(self, obj, data):
        return self.user.is_superuser or self.check_related('organization', Organization, data, obj=obj, role_field='admin_role', mandatory=True)

    def can_delete(self, obj):
        return self.user.is_superuser or obj.organization in self.user.admin_of_organizations

    def can_add(self, data):
        if self.user.is_superuser:
            return True
        if not data:
            return Organization.accessible_objects(self.user, 'admin_role').exists()
        return self.check_related('organization', Organization, data, role_field='admin_role', mandatory=True)


class OAuth2TokenAccess(BaseAccess):
    """
    I can read, change or delete an app token when:
     - I am a superuser.
     - I am the admin of the organization of the application of the token.
     - I am the user of the token.
    I can create an OAuth2 app token when:
     - I have the read permission of the related application.
    I can read, change or delete a personal token when:
     - I am the user of the token
     - I am the superuser
    I can create an OAuth2 Personal Access Token when:
     - I am a user.  But I can only create a PAT for myself.
    """

    model = OAuth2AccessToken

    select_related = ('user', 'application')
    prefetch_related = ('refresh_token',)

    def filtered_queryset(self):
        from django.db.models import Q
        org_access_qs = Organization.objects.filter(Q(admin_role__members=self.user) | Q(auditor_role__members=self.user))
        return self.model.objects.filter(application__organization__in=org_access_qs) | self.model.objects.filter(user__id=self.user.pk)

    def can_delete(self, obj):
        if (self.user.is_superuser) | (obj.user == self.user):
            return True
        elif not obj.application:
            return False
        return self.user in obj.application.organization.admin_role

    def can_change(self, obj, data):
        return self.can_delete(obj)

    def can_add(self, data):
        if 'application' in data:
            app = get_object_from_data('application', OAuth2Application, data)
            if app is None:
                return True
            return OAuth2ApplicationAccess(self.user).can_read(app)
        return True
