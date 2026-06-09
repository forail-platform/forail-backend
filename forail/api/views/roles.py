# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.utils.translation import gettext_lazy as _

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from forail.main.utils import get_object_or_400
from forail.api.generics import (
    ListAPIView,
    RetrieveAPIView,
    SubListAPIView,
    SubListAttachDetachAPIView,
)
from forail.api import serializers
from forail.main import models


class RoleList(ListAPIView):
    deprecated = True
    model = models.Role
    serializer_class = serializers.RoleSerializer
    permission_classes = (IsAuthenticated,)
    search_fields = ('role_field', 'content_type__model')


class RoleDetail(RetrieveAPIView):
    deprecated = True
    model = models.Role
    serializer_class = serializers.RoleSerializer


class RoleUsersList(SubListAttachDetachAPIView):
    deprecated = True
    model = models.User
    serializer_class = serializers.UserSerializer
    parent_model = models.Role
    relationship = 'members'
    ordering = ('username',)

    def get_queryset(self):
        role = self.get_parent_object()
        self.check_parent_access(role)
        return role.members.all()

    def post(self, request, *args, **kwargs):
        # Forbid implicit user creation here
        sub_id = request.data.get('id', None)
        if not sub_id:
            return super(RoleUsersList, self).post(request)

        user = get_object_or_400(models.User, pk=sub_id)
        role = self.get_parent_object()

        content_types = ContentType.objects.get_for_models(models.Organization, models.Team, models.Credential)  # dict of {model: content_type}
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

        return super(RoleUsersList, self).post(request, *args, **kwargs)


class RoleTeamsList(SubListAttachDetachAPIView):
    deprecated = True
    model = models.Team
    serializer_class = serializers.TeamSerializer
    parent_model = models.Role
    relationship = 'member_role.parents'
    permission_classes = (IsAuthenticated,)

    def get_queryset(self):
        role = self.get_parent_object()
        self.check_parent_access(role)
        return models.Team.objects.filter(member_role__children=role)

    def post(self, request, pk, *args, **kwargs):
        sub_id = request.data.get('id', None)
        if not sub_id:
            return super(RoleTeamsList, self).post(request)

        team = get_object_or_400(models.Team, pk=sub_id)
        role = models.Role.objects.get(pk=self.kwargs['pk'])

        organization_content_type = ContentType.objects.get_for_model(models.Organization)
        if role.content_type == organization_content_type and role.role_field in ['member_role', 'admin_role']:
            data = dict(msg=_("You cannot assign an Organization participation role as a child role for a Team."))
            return Response(data, status=status.HTTP_400_BAD_REQUEST)

        credential_content_type = ContentType.objects.get_for_model(models.Credential)
        if role.content_type == credential_content_type:
            if not role.content_object.organization or role.content_object.organization.id != team.organization.id:
                data = dict(msg=_("You cannot grant credential access to a team when the Organization field isn't set, or belongs to a different organization"))
                return Response(data, status=status.HTTP_400_BAD_REQUEST)

        action = 'attach'
        if request.data.get('disassociate', None):
            action = 'unattach'

        if role.is_singleton() and action == 'attach':
            data = dict(msg=_("You cannot grant system-level permissions to a team."))
            return Response(data, status=status.HTTP_400_BAD_REQUEST)

        if not request.user.can_access(self.parent_model, action, role, team, self.relationship, request.data, skip_sub_obj_read_check=False):
            raise PermissionDenied()
        if request.data.get('disassociate', None):
            team.member_role.children.remove(role)
        else:
            team.member_role.children.add(role)

        return Response(status=status.HTTP_204_NO_CONTENT)


class RoleParentsList(SubListAPIView):
    deprecated = True
    model = models.Role
    serializer_class = serializers.RoleSerializer
    parent_model = models.Role
    relationship = 'parents'
    permission_classes = (IsAuthenticated,)
    search_fields = ('role_field', 'content_type__model')

    def get_queryset(self):
        role = models.Role.objects.get(pk=self.kwargs['pk'])
        return models.Role.filter_visible_roles(self.request.user, role.parents.all())


class RoleChildrenList(SubListAPIView):
    deprecated = True
    model = models.Role
    serializer_class = serializers.RoleSerializer
    parent_model = models.Role
    relationship = 'children'
    permission_classes = (IsAuthenticated,)
    search_fields = ('role_field', 'content_type__model')

    def get_queryset(self):
        role = models.Role.objects.get(pk=self.kwargs['pk'])
        return models.Role.filter_visible_roles(self.request.user, role.children.all())
