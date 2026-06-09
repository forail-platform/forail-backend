# Copyright (c) 2015 Ansible, Inc.
# Copyright (c) 2026 Krstan Vjestica / Forail Project
# All Rights Reserved.

"""Organization, Team, and Role serializers for the Forail API."""

# Django
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.utils.translation import gettext_lazy as _

# Django REST Framework
from rest_framework import serializers

# django-ansible-base
from ansible_base.lib.utils.models import get_type_for_model
from ansible_base.rbac.models import RoleEvaluation, ObjectRole
from ansible_base.rbac import permission_registry

# AWX
from forail.main.constants import org_role_to_permission
from forail.main.models import (
    Organization,
    Role,
    Team,
)
from forail.main.models.rbac import get_role_codenames, to_permissions, get_role_from_object_role
from forail.main.fields import ImplicitRoleField
from forail.api.serializers.base import BaseSerializer, reverse_gfk
from forail.api.serializers.users import UserSerializer


class OrganizationSerializer(BaseSerializer):
    show_capabilities = ['edit', 'delete']

    class Meta:
        model = Organization
        fields = ('*', 'max_hosts', 'custom_virtualenv', 'default_environment')
        read_only_fields = ('*', 'custom_virtualenv')

    def get_related(self, obj):
        res = super(OrganizationSerializer, self).get_related(obj)
        res.update(
            execution_environments=self.reverse('api:organization_execution_environments_list', kwargs={'pk': obj.pk}),
            projects=self.reverse('api:organization_projects_list', kwargs={'pk': obj.pk}),
            inventories=self.reverse('api:organization_inventories_list', kwargs={'pk': obj.pk}),
            job_templates=self.reverse('api:organization_job_templates_list', kwargs={'pk': obj.pk}),
            workflow_job_templates=self.reverse('api:organization_workflow_job_templates_list', kwargs={'pk': obj.pk}),
            users=self.reverse('api:organization_users_list', kwargs={'pk': obj.pk}),
            admins=self.reverse('api:organization_admins_list', kwargs={'pk': obj.pk}),
            teams=self.reverse('api:organization_teams_list', kwargs={'pk': obj.pk}),
            credentials=self.reverse('api:organization_credential_list', kwargs={'pk': obj.pk}),
            applications=self.reverse('api:organization_applications_list', kwargs={'pk': obj.pk}),
            activity_stream=self.reverse('api:organization_activity_stream_list', kwargs={'pk': obj.pk}),
            notification_templates=self.reverse('api:organization_notification_templates_list', kwargs={'pk': obj.pk}),
            notification_templates_started=self.reverse('api:organization_notification_templates_started_list', kwargs={'pk': obj.pk}),
            notification_templates_success=self.reverse('api:organization_notification_templates_success_list', kwargs={'pk': obj.pk}),
            notification_templates_error=self.reverse('api:organization_notification_templates_error_list', kwargs={'pk': obj.pk}),
            notification_templates_approvals=self.reverse('api:organization_notification_templates_approvals_list', kwargs={'pk': obj.pk}),
            object_roles=self.reverse('api:organization_object_roles_list', kwargs={'pk': obj.pk}),
            access_list=self.reverse('api:organization_access_list', kwargs={'pk': obj.pk}),
            instance_groups=self.reverse('api:organization_instance_groups_list', kwargs={'pk': obj.pk}),
            galaxy_credentials=self.reverse('api:organization_galaxy_credentials_list', kwargs={'pk': obj.pk}),
        )
        if obj.default_environment:
            res['default_environment'] = self.reverse('api:execution_environment_detail', kwargs={'pk': obj.default_environment_id})
        return res

    def get_summary_fields(self, obj):
        summary_dict = super(OrganizationSerializer, self).get_summary_fields(obj)
        counts_dict = self.context.get('related_field_counts', None)
        if counts_dict is not None and summary_dict is not None:
            if obj.id not in counts_dict:
                summary_dict['related_field_counts'] = {'inventories': 0, 'teams': 0, 'users': 0, 'job_templates': 0, 'admins': 0, 'projects': 0}
            else:
                summary_dict['related_field_counts'] = counts_dict[obj.id]

        for key in ('admin_role', 'member_role'):
            if key in summary_dict.get('object_roles', {}):
                summary_dict['object_roles'][key]['user_only'] = True

        return summary_dict

    def validate(self, attrs):
        obj = self.instance
        view = self.context['view']

        obj_limit = getattr(obj, 'max_hosts', None)
        api_limit = attrs.get('max_hosts')

        if not view.request.user.is_superuser:
            if api_limit is not None and api_limit != obj_limit:
                raise serializers.ValidationError(_('Cannot change max_hosts.'))

        return super(OrganizationSerializer, self).validate(attrs)


class TeamSerializer(BaseSerializer):
    show_capabilities = ['edit', 'delete']

    class Meta:
        model = Team
        fields = ('*', 'organization')

    def get_related(self, obj):
        res = super(TeamSerializer, self).get_related(obj)
        res.update(
            dict(
                projects=self.reverse('api:team_projects_list', kwargs={'pk': obj.pk}),
                users=self.reverse('api:team_users_list', kwargs={'pk': obj.pk}),
                credentials=self.reverse('api:team_credentials_list', kwargs={'pk': obj.pk}),
                roles=self.reverse('api:team_roles_list', kwargs={'pk': obj.pk}),
                object_roles=self.reverse('api:team_object_roles_list', kwargs={'pk': obj.pk}),
                activity_stream=self.reverse('api:team_activity_stream_list', kwargs={'pk': obj.pk}),
                access_list=self.reverse('api:team_access_list', kwargs={'pk': obj.pk}),
            )
        )
        if obj.organization:
            res['organization'] = self.reverse('api:organization_detail', kwargs={'pk': obj.organization.pk})
        return res

    def to_representation(self, obj):
        ret = super(TeamSerializer, self).to_representation(obj)
        if obj is not None and 'organization' in ret and not obj.organization:
            ret['organization'] = None
        return ret


class RoleSerializer(BaseSerializer):
    class Meta:
        model = Role
        fields = ('*', '-created', '-modified')
        read_only_fields = ('id', 'role_field', 'description', 'name')

    def to_representation(self, obj):
        ret = super(RoleSerializer, self).to_representation(obj)

        if obj.object_id:
            content_object = obj.content_object
            if hasattr(content_object, 'username'):
                ret['summary_fields']['resource_name'] = obj.content_object.username
            if hasattr(content_object, 'name'):
                ret['summary_fields']['resource_name'] = obj.content_object.name
            content_model = obj.content_type.model_class()
            ret['summary_fields']['resource_type'] = get_type_for_model(content_model)
            ret['summary_fields']['resource_type_display_name'] = content_model._meta.verbose_name.title()
            ret['summary_fields']['resource_id'] = obj.object_id

        return ret

    def get_related(self, obj):
        ret = super(RoleSerializer, self).get_related(obj)
        ret['users'] = self.reverse('api:role_users_list', kwargs={'pk': obj.pk})
        ret['teams'] = self.reverse('api:role_teams_list', kwargs={'pk': obj.pk})
        try:
            if obj.content_object:
                ret.update(reverse_gfk(obj.content_object, self.context.get('request')))
        except AttributeError:
            pass
        return ret


class RoleSerializerWithParentAccess(RoleSerializer):
    show_capabilities = ['unattach']


class ResourceAccessListElementSerializer(UserSerializer):
    show_capabilities = []

    def to_representation(self, user):
        """
        With this method we derive "direct" and "indirect" access lists. Contained
        in the direct access list are all the roles the user is a member of, and
        all of the roles that are directly granted to any teams that the user is a
        member of.

        The indirect access list is a list of all of the roles that the user is
        a member of that are ancestors of any roles that grant permissions to
        the resource.
        """
        ret = super(ResourceAccessListElementSerializer, self).to_representation(user)
        obj = self.context['view'].get_parent_object()
        if self.context['view'].request is not None:
            requesting_user = self.context['view'].request.user
        else:
            requesting_user = None

        if 'summary_fields' not in ret:
            ret['summary_fields'] = {}

        team_content_type = ContentType.objects.get_for_model(Team)
        content_type = ContentType.objects.get_for_model(obj)

        reversed_org_map = {}
        for k, v in org_role_to_permission.items():
            reversed_org_map[v] = k
        reversed_role_map = {}
        for k, v in to_permissions.items():
            reversed_role_map[v] = k

        def get_roles_from_perms(perm_list):
            """given a list of permission codenames return a list of role names"""
            role_names = set()
            for codename in perm_list:
                action = codename.split('_', 1)[0]
                if action in reversed_role_map:
                    role_names.add(reversed_role_map[action])
                elif codename in reversed_org_map:
                    if isinstance(obj, Organization):
                        role_names.add(reversed_org_map[codename])
                        if 'view_organization' not in role_names:
                            role_names.add('read_role')
            return list(role_names)

        def format_role_perm(role):
            role_dict = {'id': role.id, 'name': role.name, 'description': role.description}
            try:
                role_dict['resource_name'] = role.content_object.name
                role_dict['resource_type'] = get_type_for_model(role.content_type.model_class())
                role_dict['related'] = reverse_gfk(role.content_object, self.context.get('request'))
            except AttributeError:
                pass
            if role.content_type is not None:
                role_dict['user_capabilities'] = {
                    'unattach': requesting_user.can_access(Role, 'unattach', role, user, 'members', data={}, skip_sub_obj_read_check=False)
                }
            else:
                role_dict['user_capabilities'] = {'unattach': False}

            model_name = content_type.model
            if isinstance(obj, Organization):
                descendant_perms = [codename for codename in get_role_codenames(role) if codename.endswith(model_name) or codename.startswith('add_')]
            else:
                descendant_perms = [codename for codename in get_role_codenames(role) if codename.endswith(model_name)]

            return {'role': role_dict, 'descendant_roles': get_roles_from_perms(descendant_perms)}

        def format_team_role_perm(naive_team_role, permissive_role_ids):
            ret = []
            team = naive_team_role.content_object
            team_role = naive_team_role
            if naive_team_role.role_field == 'admin_role':
                team_role = team.member_role
            for role in team_role.children.filter(id__in=permissive_role_ids).all():
                role_dict = {
                    'id': role.id,
                    'name': role.name,
                    'description': role.description,
                    'team_id': team_role.object_id,
                    'team_name': team_role.content_object.name,
                    'team_organization_name': team_role.content_object.organization.name,
                }
                if role.content_type is not None:
                    role_dict['resource_name'] = role.content_object.name
                    role_dict['resource_type'] = get_type_for_model(role.content_type.model_class())
                    role_dict['related'] = reverse_gfk(role.content_object, self.context.get('request'))
                    role_dict['user_capabilities'] = {
                        'unattach': requesting_user.can_access(Role, 'unattach', role, team_role, 'parents', data={}, skip_sub_obj_read_check=False)
                    }
                else:
                    role_dict['user_capabilities'] = {'unattach': False}

                descendant_perms = list(
                    RoleEvaluation.objects.filter(role__in=team.has_roles.all(), object_id=obj.id, content_type_id=content_type.id)
                    .values_list('codename', flat=True)
                    .distinct()
                )

                ret.append({'role': role_dict, 'descendant_roles': get_roles_from_perms(descendant_perms)})
            return ret

        gfk_kwargs = dict(content_type_id=content_type.id, object_id=obj.id)
        direct_permissive_role_ids = Role.objects.filter(**gfk_kwargs).values_list('id', flat=True)

        if settings.ANSIBLE_BASE_ROLE_SYSTEM_ACTIVATED:
            ret['summary_fields']['direct_access'] = []
            ret['summary_fields']['indirect_access'] = []

            new_roles_seen = set()
            all_team_roles = set()
            all_permissive_role_ids = set()
            for evaluation in RoleEvaluation.objects.filter(role__in=user.has_roles.all(), **gfk_kwargs).prefetch_related('role'):
                new_role = evaluation.role
                if new_role.id in new_roles_seen:
                    continue
                new_roles_seen.add(new_role.id)
                old_role = get_role_from_object_role(new_role)
                all_permissive_role_ids.add(old_role.id)

                if int(new_role.object_id) == obj.id and new_role.content_type_id == content_type.id:
                    ret['summary_fields']['direct_access'].append(format_role_perm(old_role))
                elif new_role.content_type_id == team_content_type.id:
                    all_team_roles.add(old_role)
                else:
                    ret['summary_fields']['indirect_access'].append(format_role_perm(old_role))

            user_teams_qs = permission_registry.team_model.objects.filter(member_roles__in=ObjectRole.objects.filter(users=user))
            team_obj_roles = ObjectRole.objects.filter(teams__in=user_teams_qs)
            for evaluation in RoleEvaluation.objects.filter(role__in=team_obj_roles, **gfk_kwargs).prefetch_related('role'):
                new_role = evaluation.role
                if new_role.id in new_roles_seen:
                    continue
                new_roles_seen.add(new_role.id)
                old_role = get_role_from_object_role(new_role)
                all_permissive_role_ids.add(old_role.id)

            if user.is_superuser:
                ret['summary_fields'].setdefault('indirect_access', [])
                all_role_names = [field.name for field in obj._meta.get_fields() if isinstance(field, ImplicitRoleField)]
                ret['summary_fields']['indirect_access'].append(
                    {
                        "role": {
                            "id": None,
                            "name": _("System Administrator"),
                            "description": _("Can manage all aspects of the system"),
                            "user_capabilities": {"unattach": False},
                        },
                        "descendant_roles": all_role_names,
                    }
                )
            elif user.is_system_auditor:
                ret['summary_fields'].setdefault('indirect_access', [])
                ret['summary_fields']['indirect_access'].append(
                    {
                        "role": {
                            "id": None,
                            "name": _("System Auditor"),
                            "description": _("Can view all aspects of the system"),
                            "user_capabilities": {"unattach": False},
                        },
                        "descendant_roles": ["read_role"],
                    }
                )

            ret['summary_fields']['direct_access'].extend([y for x in (format_team_role_perm(r, all_permissive_role_ids) for r in all_team_roles) for y in x])

            return ret

        all_permissive_role_ids = Role.objects.filter(content_type=content_type, object_id=obj.id).values_list('ancestors__id', flat=True)

        direct_access_roles = user.roles.filter(id__in=direct_permissive_role_ids).all()

        direct_team_roles = Role.objects.filter(content_type=team_content_type, members=user, children__in=direct_permissive_role_ids)
        if content_type == team_content_type:
            direct_team_roles = direct_team_roles.exclude(children__content_type=team_content_type, children__object_id=obj.id)

        indirect_team_roles = Role.objects.filter(content_type=team_content_type, members=user, children__in=all_permissive_role_ids).exclude(
            id__in=direct_team_roles
        )

        indirect_access_roles = (
            user.roles.filter(id__in=all_permissive_role_ids)
            .exclude(id__in=direct_permissive_role_ids)
            .exclude(id__in=direct_team_roles)
            .exclude(id__in=indirect_team_roles)
        )

        ret['summary_fields']['direct_access'] = (
            [format_role_perm(r) for r in direct_access_roles.distinct()]
            + [y for x in (format_team_role_perm(r, direct_permissive_role_ids) for r in direct_team_roles.distinct()) for y in x]
            + [y for x in (format_team_role_perm(r, all_permissive_role_ids) for r in indirect_team_roles.distinct()) for y in x]
        )

        ret['summary_fields']['indirect_access'] = [format_role_perm(r) for r in indirect_access_roles.distinct()]

        return ret
