# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

from django.contrib.auth.models import User

from forail.main.access.base import (
    BaseAccess,
    check_superuser,
    check_user_access,
    get_object_from_data,
)
from forail.main.models import (
    Credential,
    CredentialInputSource,
    CredentialType,
    Organization,
    Team,
)


class CredentialTypeAccess(BaseAccess):
    """
    I can see credentials types when:
     - I'm authenticated
    I can create when:
     - I'm a superuser:
    I can change when:
     - I'm a superuser and the type is not "managed"
    """

    model = CredentialType
    prefetch_related = (
        'created_by',
        'modified_by',
    )

    def can_use(self, obj):
        return True

    def filtered_queryset(self):
        return self.model.objects.all()


class CredentialAccess(BaseAccess):
    """
    I can see credentials when:
     - I'm a superuser.
     - It's a user credential and it's my credential.
     - It's a user credential and I'm an admin of an organization where that
       user is a member.
     - It's a user credential and I'm a credential_admin of an organization
       where that user is a member.
     - It's a team credential and I'm an admin of the team's organization.
     - It's a team credential and I'm a credential admin of the team's
       organization.
     - It's a team credential and I'm a member of the team.
    I can change/delete when:
     - I'm a superuser.
     - It's my user credential.
     - It's a user credential for a user in an org I admin.
     - It's a team credential for a team in an org I admin.
    """

    model = Credential
    select_related = (
        'created_by',
        'modified_by',
    )
    prefetch_related = ('admin_role', 'use_role', 'read_role', 'admin_role__parents', 'admin_role__members', 'credential_type', 'organization')

    def filtered_queryset(self):
        return self.model.accessible_objects(self.user, 'read_role')

    @check_superuser
    def can_add(self, data):
        if not data:  # So the browseable API will work
            return True
        if data and data.get('user', None):
            user_obj = get_object_from_data('user', User, data)
            from forail.main.access.users import UserAccess
            if not bool(self.user == user_obj or UserAccess(self.user).can_admin(user_obj, None, check_setting=False)):
                return False
        if data and data.get('team', None):
            team_obj = get_object_from_data('team', Team, data)
            if not check_user_access(self.user, Team, 'change', team_obj, None):
                return False
        if data and data.get('organization', None):
            organization_obj = get_object_from_data('organization', Organization, data)
            if not any([check_user_access(self.user, Organization, 'change', organization_obj, None), self.user in organization_obj.credential_admin_role]):
                return False
        if not any(data.get(key, None) for key in ('user', 'team', 'organization')):
            return False  # you have to provide 1 owner field
        return True

    @check_superuser
    def can_use(self, obj):
        return self.user in obj.use_role

    @check_superuser
    def can_change(self, obj, data):
        if not obj:
            return False
        return self.user in obj.admin_role and self.check_related('organization', Organization, data, obj=obj, role_field='credential_admin_role')

    def can_delete(self, obj):
        # Unassociated credentials may be marked deleted by anyone, though we
        # shouldn't ever end up with those.
        # if obj.user is None and obj.team is None:
        #    return True
        return self.can_change(obj, None)

    def get_user_capabilities(self, obj, **kwargs):
        user_capabilities = super(CredentialAccess, self).get_user_capabilities(obj, **kwargs)
        user_capabilities['use'] = self.can_use(obj)
        if getattr(obj, 'managed', False) is True:
            user_capabilities['edit'] = user_capabilities['delete'] = False
        return user_capabilities


class CredentialInputSourceAccess(BaseAccess):
    """
    I can see a CredentialInputSource when:
     - I can see the associated target_credential
    I can create/change a CredentialInputSource when:
     - I'm an admin of the associated target_credential
     - I have use access to the associated source credential
    I can delete a CredentialInputSource when:
     - I'm an admin of the associated target_credential
    """

    model = CredentialInputSource
    select_related = ('target_credential', 'source_credential')

    def filtered_queryset(self):
        return CredentialInputSource.objects.filter(target_credential__in=Credential.accessible_pk_qs(self.user, 'read_role'))

    @check_superuser
    def can_add(self, data):
        return self.check_related('target_credential', Credential, data, role_field='admin_role') and self.check_related(
            'source_credential', Credential, data, role_field='use_role'
        )

    @check_superuser
    def can_change(self, obj, data):
        if self.can_add(data) is False:
            return False

        return self.user in obj.target_credential.admin_role and self.user in obj.source_credential.use_role

    @check_superuser
    def can_delete(self, obj):
        return self.user in obj.target_credential.admin_role
