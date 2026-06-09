# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _

from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework import status

from ansible_base.rbac.models import RoleEvaluation, ObjectRole

from forail.main.models.rbac import get_role_definition
from forail.main.utils import get_object_or_400
from forail.api.generics import (
    BaseUsersList,
    ListCreateAPIView,
    ResourceAccessList,
    RetrieveUpdateDestroyAPIView,
    SubListAPIView,
    SubListAttachDetachAPIView,
)
from forail.api.metadata import RoleMetadata
from forail.api.views.mixin import immutablesharedfields
from forail.api import serializers
from forail.main import models


@immutablesharedfields
class TeamList(ListCreateAPIView):
    model = models.Team
    serializer_class = serializers.TeamSerializer


@immutablesharedfields
class TeamDetail(RetrieveUpdateDestroyAPIView):
    model = models.Team
    serializer_class = serializers.TeamSerializer


@immutablesharedfields
class TeamUsersList(BaseUsersList):
    model = models.User
    serializer_class = serializers.UserSerializer
    parent_model = models.Team
    relationship = 'member_role.members'
    ordering = ('username',)


class TeamRolesList(SubListAttachDetachAPIView):
    deprecated = True
    model = models.Role
    serializer_class = serializers.RoleSerializerWithParentAccess
    metadata_class = RoleMetadata
    parent_model = models.Team
    relationship = 'member_role.children'
    search_fields = ('role_field', 'content_type__model')

    def get_queryset(self):
        team = get_object_or_404(models.Team, pk=self.kwargs['pk'])
        if not self.request.user.can_access(models.Team, 'read', team):
            raise PermissionDenied()
        return models.Role.filter_visible_roles(self.request.user, team.member_role.children.all().exclude(pk=team.read_role.pk))

    def post(self, request, *args, **kwargs):
        sub_id = request.data.get('id', None)
        if not sub_id:
            return super(TeamRolesList, self).post(request)

        role = get_object_or_400(models.Role, pk=sub_id)
        org_content_type = ContentType.objects.get_for_model(models.Organization)
        if role.content_type == org_content_type and role.role_field in ['member_role', 'admin_role']:
            data = dict(msg=_("You cannot assign an Organization participation role as a child role for a Team."))
            return Response(data, status=status.HTTP_400_BAD_REQUEST)

        if role.is_singleton():
            data = dict(msg=_("You cannot grant system-level permissions to a team."))
            return Response(data, status=status.HTTP_400_BAD_REQUEST)

        team = get_object_or_404(models.Team, pk=self.kwargs['pk'])
        credential_content_type = ContentType.objects.get_for_model(models.Credential)
        if role.content_type == credential_content_type:
            if not role.content_object.organization or role.content_object.organization.id != team.organization.id:
                data = dict(msg=_("You cannot grant credential access to a team when the Organization field isn't set, or belongs to a different organization"))
                return Response(data, status=status.HTTP_400_BAD_REQUEST)

        return super(TeamRolesList, self).post(request, *args, **kwargs)


class TeamObjectRolesList(SubListAPIView):
    deprecated = True
    model = models.Role
    serializer_class = serializers.RoleSerializer
    parent_model = models.Team
    search_fields = ('role_field', 'content_type__model')
    deprecated = True

    def get_queryset(self):
        po = self.get_parent_object()
        content_type = ContentType.objects.get_for_model(self.parent_model)
        return models.Role.objects.filter(content_type=content_type, object_id=po.pk)


class TeamProjectsList(SubListAPIView):
    model = models.Project
    serializer_class = serializers.ProjectSerializer
    parent_model = models.Team

    def get_queryset(self):
        team = self.get_parent_object()
        self.check_parent_access(team)
        model_ct = ContentType.objects.get_for_model(self.model)
        parent_ct = ContentType.objects.get_for_model(self.parent_model)

        rd = get_role_definition(team.member_role)
        role = ObjectRole.objects.filter(object_id=team.id, content_type=parent_ct, role_definition=rd).first()
        if role is None:
            # Team has no permissions, therefore team has no projects
            return self.model.objects.none()
        else:
            project_qs = self.model.accessible_objects(self.request.user, 'read_role')
            return project_qs.filter(id__in=RoleEvaluation.objects.filter(content_type_id=model_ct.id, role=role).values_list('object_id'))


class TeamActivityStreamList(SubListAPIView):
    model = models.ActivityStream
    serializer_class = serializers.ActivityStreamSerializer
    parent_model = models.Team
    relationship = 'activitystream_set'
    search_fields = ('changes',)

    def get_queryset(self):
        parent = self.get_parent_object()
        self.check_parent_access(parent)

        qs = self.request.user.get_queryset(self.model)

        return qs.filter(
            Q(team=parent)
            | Q(
                project__in=RoleEvaluation.objects.filter(
                    role__in=parent.has_roles.all(), content_type_id=ContentType.objects.get_for_model(models.Project).id, codename='view_project'
                )
                .values_list('object_id')
                .distinct()
            )
            | Q(
                credential__in=RoleEvaluation.objects.filter(
                    role__in=parent.has_roles.all(), content_type_id=ContentType.objects.get_for_model(models.Credential).id, codename='view_credential'
                )
                .values_list('object_id')
                .distinct()
            )
        )


class TeamAccessList(ResourceAccessList):
    model = models.User  # needs to be User for AccessLists's
    parent_model = models.Team


