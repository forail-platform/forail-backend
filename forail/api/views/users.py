# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from forail.main.utils import get_object_or_400
from forail.api.generics import (
    ListAPIView,
    ListCreateAPIView,
    ResourceAccessList,
    RetrieveUpdateDestroyAPIView,
    SubListAPIView,
    SubListAttachDetachAPIView,
)
from forail.api.views.mixin import OrganizationCountsMixin, immutablesharedfields
from forail.api.metadata import RoleMetadata
from forail.api.permissions import UserPermission
from forail.api import serializers
from forail.main import models


@immutablesharedfields
class UserList(ListCreateAPIView):
    model = models.User
    serializer_class = serializers.UserSerializer
    permission_classes = (UserPermission,)
    ordering = ('username',)


class UserMeList(ListAPIView):
    model = models.User
    serializer_class = serializers.UserSerializer
    name = _('Me')
    ordering = ('username',)

    def get_queryset(self):
        return self.model.objects.filter(pk=self.request.user.pk)


@immutablesharedfields
class UserDetail(RetrieveUpdateDestroyAPIView):
    model = models.User
    serializer_class = serializers.UserSerializer

    def update_filter(self, request, *args, **kwargs):
        '''make sure non-read-only fields that can only be edited by admins, are only edited by admins'''
        obj = self.get_object()
        can_change = request.user.can_access(models.User, 'change', obj, request.data)
        can_admin = request.user.can_access(models.User, 'admin', obj, request.data)

        su_only_edit_fields = ('is_superuser', 'is_system_auditor')
        admin_only_edit_fields = ('username', 'is_active')

        fields_to_check = ()
        if not request.user.is_superuser:
            fields_to_check += su_only_edit_fields

        if can_change and not can_admin:
            fields_to_check += admin_only_edit_fields

        bad_changes = {}
        for field in fields_to_check:
            left = getattr(obj, field, None)
            right = request.data.get(field, None)
            if left is not None and right is not None and left != right:
                bad_changes[field] = (left, right)
        if bad_changes:
            raise PermissionDenied(_('Cannot change %s.') % ', '.join(bad_changes.keys()))

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        can_delete = request.user.can_access(models.User, 'delete', obj)
        if not can_delete:
            raise PermissionDenied(_('Cannot delete user.'))
        return super(UserDetail, self).destroy(request, *args, **kwargs)


class UserTeamsList(SubListAPIView):
    model = models.Team
    serializer_class = serializers.TeamSerializer
    parent_model = models.User

    def get_queryset(self):
        u = get_object_or_404(models.User, pk=self.kwargs['pk'])
        if not self.request.user.can_access(models.User, 'read', u):
            raise PermissionDenied()
        return models.Team.accessible_objects(self.request.user, 'read_role').filter(Q(member_role__members=u) | Q(admin_role__members=u)).distinct()


class UserRolesList(SubListAttachDetachAPIView):
    deprecated = True
    model = models.Role
    serializer_class = serializers.RoleSerializerWithParentAccess
    metadata_class = RoleMetadata
    parent_model = models.User
    relationship = 'roles'
    permission_classes = (IsAuthenticated,)
    search_fields = ('role_field', 'content_type__model')

    def get_queryset(self):
        u = get_object_or_404(models.User, pk=self.kwargs['pk'])
        if not self.request.user.can_access(models.User, 'read', u):
            raise PermissionDenied()
        content_type = ContentType.objects.get_for_model(models.User)

        return models.Role.filter_visible_roles(self.request.user, u.roles.all()).exclude(content_type=content_type, object_id=u.id)

    def post(self, request, *args, **kwargs):
        sub_id = request.data.get('id', None)
        if not sub_id:
            return super(UserRolesList, self).post(request)

        user = get_object_or_400(models.User, pk=self.kwargs['pk'])
        role = get_object_or_400(models.Role, pk=sub_id)

        content_types = ContentType.objects.get_for_models(models.Organization, models.Team, models.Credential)  # dict of {model: content_type}
        # Prevent user to be associated with team/org when ALLOW_LOCAL_RESOURCE_MANAGEMENT is False
        if not settings.ALLOW_LOCAL_RESOURCE_MANAGEMENT:
            for model in [models.Organization, models.Team]:
                ct = content_types[model]
                if role.content_type == ct and role.role_field in ['member_role', 'admin_role']:
                    data = dict(msg=_(f"Cannot directly modify user membership to {ct.model}. Direct shared resource management disabled"))
                    return Response(data, status=status.HTTP_403_FORBIDDEN)

        credential_content_type = content_types[models.Credential]
        if role.content_type == credential_content_type:
            if 'disassociate' not in request.data and role.content_object.organization and user not in role.content_object.organization.member_role:
                data = dict(msg=_("You cannot grant credential access to a user not in the credentials' organization"))
                return Response(data, status=status.HTTP_400_BAD_REQUEST)

            if not role.content_object.organization and not request.user.is_superuser:
                data = dict(msg=_("You cannot grant private credential access to another user"))
                return Response(data, status=status.HTTP_400_BAD_REQUEST)

        return super(UserRolesList, self).post(request, *args, **kwargs)

    def check_parent_access(self, parent=None):
        # We hide roles that shouldn't be seen in our queryset
        return True


class UserProjectsList(SubListAPIView):
    model = models.Project
    serializer_class = serializers.ProjectSerializer
    parent_model = models.User

    def get_queryset(self):
        parent = self.get_parent_object()
        self.check_parent_access(parent)
        my_qs = models.Project.accessible_objects(self.request.user, 'read_role')
        user_qs = models.Project.accessible_objects(parent, 'read_role')
        return my_qs & user_qs


class UserOrganizationsList(OrganizationCountsMixin, SubListAPIView):
    model = models.Organization
    serializer_class = serializers.OrganizationSerializer
    parent_model = models.User
    relationship = 'organizations'

    def get_queryset(self):
        parent = self.get_parent_object()
        self.check_parent_access(parent)
        my_qs = models.Organization.accessible_objects(self.request.user, 'read_role')
        user_qs = models.Organization.objects.filter(member_role__members=parent)
        return my_qs & user_qs


class UserAdminOfOrganizationsList(OrganizationCountsMixin, SubListAPIView):
    model = models.Organization
    serializer_class = serializers.OrganizationSerializer
    parent_model = models.User
    relationship = 'admin_of_organizations'

    def get_queryset(self):
        parent = self.get_parent_object()
        self.check_parent_access(parent)
        my_qs = models.Organization.accessible_objects(self.request.user, 'read_role')
        user_qs = models.Organization.objects.filter(admin_role__members=parent)
        return my_qs & user_qs


class UserActivityStreamList(SubListAPIView):
    model = models.ActivityStream
    serializer_class = serializers.ActivityStreamSerializer
    parent_model = models.User
    relationship = 'activitystream_set'
    search_fields = ('changes',)

    def get_queryset(self):
        parent = self.get_parent_object()
        self.check_parent_access(parent)
        qs = self.request.user.get_queryset(self.model)
        return qs.filter(Q(actor=parent) | Q(user__in=[parent]))


class UserAccessList(ResourceAccessList):
    model = models.User  # needs to be User for AccessLists's
    parent_model = models.User
