# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

from functools import reduce

from django.db.models import Q, Prefetch
from django.utils.translation import gettext_lazy as _

from rest_framework.exceptions import PermissionDenied

from forail.main.access.base import (
    BaseAccess,
    NotificationAttachMixin,
    UnifiedCredentialsMixin,
    check_superuser,
    get_object_from_data,
    vars_are_encrypted,
)
from forail.main.models import (
    AdHocCommand,
    AdHocCommandEvent,
    Credential,
    ExecutionEnvironment,
    Host,
    InstanceGroup,
    Inventory,
    Job,
    JobLaunchConfig,
    JobTemplate,
    Label,
    Organization,
    Project,
    SystemJob,
    SystemJobTemplate,
    UnifiedJob,
)


class JobTemplateAccess(NotificationAttachMixin, UnifiedCredentialsMixin, BaseAccess):
    """
    I can see job templates when:
     - I have read role for the job template.
    """

    model = JobTemplate
    select_related = (
        'created_by',
        'modified_by',
        'inventory',
        'project',
        'organization',
        'next_schedule',
    )
    prefetch_related = (
        'instance_groups',
        'credentials__credential_type',
        Prefetch('labels', queryset=Label.objects.all().order_by('name')),
        Prefetch('last_job', queryset=UnifiedJob.objects.non_polymorphic()),
    )

    def filtered_queryset(self):
        return self.model.accessible_objects(self.user, 'read_role')

    def can_add(self, data):
        """
        a user can create a job template if
         - they are a superuser
         - an org admin of any org that the project is a member
         - if they are a project_admin for any org that project is a member of
         - if they have user or team
        based permissions tying the project to the inventory source for the
        given action as well as the 'create' deploy permission.
        Users who are able to create deploy jobs can also run normal and check (dry run) jobs.
        """
        if not data:  # So the browseable API will work
            return Project.accessible_objects(self.user, 'use_role').exists()

        # if reference_obj is provided, determine if it can be copied
        reference_obj = data.get('reference_obj', None)

        if self.user.is_superuser:
            return True

        def get_value(Class, field):
            if reference_obj:
                return getattr(reference_obj, field, None)
            else:
                if data and data.get(field, None):
                    return get_object_from_data(field, Class, data)
                else:
                    return None

        # If credentials is provided, the user should have use access to them.
        for pk in data.get('credentials', []):
            raise Exception('Credentials must be attached through association method.')

        # If an inventory is provided, the user should have use access.
        inventory = get_value(Inventory, 'inventory')
        if inventory:
            if self.user not in inventory.use_role:
                if self.save_messages:
                    self.messages['inventory'] = [_('You do not have use permission on Inventory')]
                return False

        if not self.check_related('execution_environment', ExecutionEnvironment, data, role_field='read_role'):
            return False

        project = get_value(Project, 'project')
        # If the user has admin access to the project (as an org admin), should
        # be able to proceed without additional checks.
        if not project:
            return False

        if self.user not in project.use_role:
            if self.save_messages:
                self.messages['project'] = [_('You do not have use permission on Project')]
            return False

        return True

    @check_superuser
    def can_copy_related(self, obj):
        """
        Check if we have access to all the credentials related to Job Templates.
        Does not verify the user's permission for any other related fields (projects, inventories, etc).
        """

        # obj.credentials.all() is accessible ONLY when object is saved (has valid id)
        credential_manager = getattr(obj, 'credentials', None) if getattr(obj, 'id', False) else Credential.objects.none()
        user_can_copy = reduce(lambda prev, cred: prev and self.user in cred.use_role, credential_manager.all(), True)
        if not user_can_copy:
            raise PermissionDenied(_('Insufficient access to Job Template credentials.'))
        return user_can_copy

    def can_start(self, obj, validate_license=True):
        # Check license.
        if validate_license:
            self.check_license()

            # Check the per-org limit
            self.check_org_host_limit({'inventory': obj.inventory})

        # Super users can start any job
        if self.user.is_superuser:
            return True

        return self.user in obj.execute_role

    def can_change(self, obj, data):
        if self.user not in obj.admin_role and not self.user.is_superuser:
            return False
        if data is None:
            return True

        data = dict(data)

        if self.changes_are_non_sensitive(obj, data):
            return True

        if not self.check_related('execution_environment', ExecutionEnvironment, data, obj=obj, role_field='read_role'):
            return False

        for required_field, cls in (('inventory', Inventory), ('project', Project)):
            is_mandatory = True
            if not getattr(obj, '{}_id'.format(required_field)):
                is_mandatory = False
            if not self.check_related(required_field, cls, data, obj=obj, role_field='use_role', mandatory=is_mandatory):
                return False
        return True

    def changes_are_non_sensitive(self, obj, data):
        """
        Return true if the changes being made are considered nonsensitive, and
        thus can be made by a job template administrator which may not have access
        to the any inventory, project, or credentials associated with the template.
        """
        allowed_fields = [
            'name',
            'description',
            'forks',
            'limit',
            'verbosity',
            'extra_vars',
            'job_tags',
            'force_handlers',
            'skip_tags',
            'ask_variables_on_launch',
            'ask_tags_on_launch',
            'ask_job_type_on_launch',
            'ask_skip_tags_on_launch',
            'ask_inventory_on_launch',
            'ask_credential_on_launch',
            'survey_enabled',
            'custom_virtualenv',
            'diff_mode',
            'timeout',
            'job_slice_count',
            # These fields are ignored, but it is convenient for QA to allow clients to post them
            'last_job_run',
            'created',
            'modified',
        ]

        for k, v in data.items():
            if k not in [x.name for x in obj._meta.concrete_fields]:
                continue
            if hasattr(obj, k) and getattr(obj, k) != v:
                if (
                    k not in allowed_fields
                    and v != getattr(obj, '%s_id' % k, None)
                    and not (hasattr(obj, '%s_id' % k) and getattr(obj, '%s_id' % k) is None and v == '')
                ):  # Equate '' to None in the case of foreign keys
                    return False
        return True

    def can_delete(self, obj):
        return self.user.is_superuser or self.user in obj.admin_role

    @check_superuser
    # object here is the job template. sub_object here is what is being attached
    def can_attach(self, obj, sub_obj, relationship, data, skip_sub_obj_read_check=False):
        if relationship == "instance_groups":
            if not obj.organization:
                return False
            return self.user in sub_obj.use_role and self.user in obj.admin_role
        return super(JobTemplateAccess, self).can_attach(obj, sub_obj, relationship, data, skip_sub_obj_read_check=skip_sub_obj_read_check)

    @check_superuser
    def can_unattach(self, obj, sub_obj, relationship, *args, **kwargs):
        if relationship == "instance_groups":
            return self.can_attach(obj, sub_obj, relationship, *args, **kwargs)
        return super(JobTemplateAccess, self).can_unattach(obj, sub_obj, relationship, *args, **kwargs)


class JobAccess(BaseAccess):
    """
    I can see jobs when:
     - I am a superuser.
     - I can see its job template
     - I am an admin or auditor of the organization which contains its inventory
     - I am an admin or auditor of the organization which contains its project
    I can delete jobs when:
     - I am an admin of the organization which contains its inventory
     - I am an admin of the organization which contains its project
    """

    model = Job
    select_related = (
        'created_by',
        'modified_by',
        'job_template',
        'inventory',
        'project',
        'project_update',
    )
    prefetch_related = (
        'organization',
        'unified_job_template',
        'instance_group',
        'credentials__credential_type',
        Prefetch('labels', queryset=Label.objects.all().order_by('name')),
    )

    def filtered_queryset(self):
        qs = self.model.objects

        qs_jt = qs.filter(job_template__in=JobTemplate.accessible_objects(self.user, 'read_role'))

        org_access_qs = Organization.objects.filter(Q(admin_role__members=self.user) | Q(auditor_role__members=self.user))
        if not org_access_qs.exists():
            return qs_jt

        return qs.filter(Q(job_template__in=JobTemplate.accessible_objects(self.user, 'read_role')) | Q(organization__in=org_access_qs)).distinct()

    def can_add(self, data, validate_license=True):
        raise NotImplementedError('Direct job creation not possible in v2 API')

    def can_change(self, obj, data):
        raise NotImplementedError('Direct job editing not supported in v2 API')

    @check_superuser
    def can_delete(self, obj):
        if not obj.organization:
            return False
        return self.user in obj.organization.admin_role

    def can_start(self, obj, validate_license=True):
        if validate_license:
            self.check_license()

            # Check the per-org limit
            self.check_org_host_limit({'inventory': obj.inventory})

        # A super user can relaunch a job
        if self.user.is_superuser:
            return True

        # Obtain prompts used to start original job
        JobLaunchConfig = obj._meta.get_field('launch_config').related_model
        try:
            config = JobLaunchConfig.objects.prefetch_related('credentials').get(job=obj)
        except JobLaunchConfig.DoesNotExist:
            config = None

        # Standard permissions model
        if obj.job_template and (self.user not in obj.job_template.execute_role):
            return False

        # Check if JT execute access (and related prompts) is sufficient
        if config and obj.job_template:
            if not config.has_user_prompts(obj.job_template):
                return True
            elif obj.created_by_id != self.user.pk and vars_are_encrypted(config.extra_data):
                # never allowed, not even for org admins
                raise PermissionDenied(_('Job was launched with secret prompts provided by another user.'))
            elif not config.has_unprompted(obj.job_template):
                if JobLaunchConfigAccess(self.user).can_add({'reference_obj': config}):
                    return True

        # Standard permissions model without job template involved
        if obj.organization and self.user in obj.organization.execute_role:
            return True
        elif not (obj.job_template or obj.organization):
            raise PermissionDenied(_('Job has been orphaned from its job template and organization.'))
        elif obj.job_template and config is not None:
            raise PermissionDenied(_('Job was launched with prompted fields you do not have access to.'))
        elif obj.job_template and config is None:
            raise PermissionDenied(_('Job was launched with unknown prompted fields. Organization admin permissions required.'))

        return False

    def get_method_capability(self, method, obj, parent_obj):
        if method == 'start':
            # Return simplistic permission, will perform detailed check on POST
            if not obj.job_template:
                return True
            return self.user in obj.job_template.execute_role
        return super(JobAccess, self).get_method_capability(method, obj, parent_obj)

    def can_cancel(self, obj):
        if not obj.can_cancel:
            return False
        # Users may always cancel their own jobs
        if self.user == obj.created_by:
            return True
        # Users with direct admin to JT may cancel jobs started by anyone
        if obj.job_template and self.user in obj.job_template.admin_role:
            return True
        # If orphaned, allow org JT admins to stop running jobs
        if not obj.job_template and obj.organization and self.user in obj.organization.job_template_admin_role:
            return True
        return False


class SystemJobTemplateAccess(BaseAccess):
    """
    I can only see/manage System Job Templates if I'm a super user
    """

    model = SystemJobTemplate

    @check_superuser
    def can_start(self, obj, validate_license=True):
        '''Only a superuser can start a job from a SystemJobTemplate'''
        return False


class SystemJobAccess(BaseAccess):
    """
    I can only see manage System Jobs if I'm a super user
    """

    model = SystemJob

    def can_start(self, obj, validate_license=True):
        return False  # no relaunching of system jobs


class JobLaunchConfigAccess(UnifiedCredentialsMixin, BaseAccess):
    """
    Launch configs must have permissions checked for
     - relaunching
     - rescheduling

    In order to create a new object with a copy of this launch config, I need:
     - use access to related inventory (if present)
     - read access to Execution Environment (if present), unless the specified ee is already in the template
     - use role to many-related credentials (if any present)
     - read access to many-related labels (if any present), unless the specified label is already in the template
     - read access to many-related instance groups (if any present), unless the specified instance group is already in the template
    """

    model = JobLaunchConfig
    select_related = 'job'
    prefetch_related = ('credentials', 'inventory')

    M2M_CHECKS = {'credentials': Credential, 'labels': Label, 'instance_groups': InstanceGroup}

    def _related_filtered_queryset(self, cls):
        if cls is Label:
            from forail.main.access.notifications import LabelAccess
            return LabelAccess(self.user).filtered_queryset()
        else:
            return cls._accessible_pk_qs(cls, self.user, 'use_role')

    def has_obj_m2m_access(self, obj):
        for relationship, cls in self.M2M_CHECKS.items():
            if getattr(obj, relationship).exclude(pk__in=self._related_filtered_queryset(cls)).exists():
                return False
        return True

    @check_superuser
    def can_add(self, data, template=None):
        # WARNING: duplicated with BulkJobLaunchSerializer, check when changing permission levels
        # This is a special case, we don't check related many-to-many elsewhere
        # launch RBAC checks use this
        if 'reference_obj' in data:
            if not self.has_obj_m2m_access(data['reference_obj']):
                return False
        else:
            for relationship, cls in self.M2M_CHECKS.items():
                if relationship in data and data[relationship]:
                    # If given model objects, only use the primary key from them
                    sub_obj_pks = [sub_obj.pk for sub_obj in data[relationship]]
                    if template:
                        for sub_obj in getattr(template, relationship).all():
                            if sub_obj.pk in sub_obj_pks:
                                sub_obj_pks.remove(sub_obj.pk)
                    if cls.objects.filter(pk__in=sub_obj_pks).exclude(pk__in=self._related_filtered_queryset(cls)).exists():
                        return False
        return self.check_related('inventory', Inventory, data, role_field='use_role') and self.check_related(
            'execution_environment', ExecutionEnvironment, data, role_field='read_role'
        )

    @check_superuser
    def can_use(self, obj):
        return (
            self.has_obj_m2m_access(obj)
            and self.check_related('inventory', Inventory, {}, obj=obj, role_field='use_role', mandatory=True)
            and self.check_related('execution_environment', ExecutionEnvironment, {}, obj=obj, role_field='read_role')
        )

    def can_change(self, obj, data):
        return self.check_related('inventory', Inventory, data, obj=obj, role_field='use_role') and self.check_related(
            'execution_environment', ExecutionEnvironment, data, obj=obj, role_field='read_role'
        )


class AdHocCommandAccess(BaseAccess):
    """
    I can only see/run ad hoc commands when:
    - I am a superuser.
    - I have read access to the inventory
    """

    model = AdHocCommand
    select_related = (
        'created_by',
        'modified_by',
        'inventory',
        'credential',
    )

    def filtered_queryset(self):
        return self.model.objects.filter(inventory__in=Inventory.accessible_pk_qs(self.user, 'read_role'))

    def can_add(self, data, validate_license=True):
        if not data:  # So the browseable API will work
            return True

        if validate_license:
            self.check_license()

            # Check the per-org limit
            self.check_org_host_limit(data)

        # If a credential is provided, the user should have use access to it.
        if not self.check_related('credential', Credential, data, role_field='use_role'):
            return False

        # Check that the user has the run ad hoc command permission on the
        # given inventory.
        if not self.check_related('inventory', Inventory, data, role_field='adhoc_role'):
            return False

        return True

    def can_change(self, obj, data):
        return False

    @check_superuser
    def can_delete(self, obj):
        return obj.inventory is not None and self.user in obj.inventory.organization.admin_role

    def can_start(self, obj, validate_license=True):
        return self.can_add(
            {
                'credential': obj.credential_id,
                'inventory': obj.inventory_id,
            },
            validate_license=validate_license,
        )

    def can_cancel(self, obj):
        if not obj.can_cancel:
            return False
        if self.user == obj.created_by:
            return True
        return obj.inventory is not None and self.user in obj.inventory.admin_role


class AdHocCommandEventAccess(BaseAccess):
    """
    I can see ad hoc command event records whenever I can read both ad hoc
    command and host.
    """

    model = AdHocCommandEvent

    def get_queryset(self):
        qs = self.model.objects.distinct()
        qs = qs.select_related('ad_hoc_command', 'host')

        if self.user.is_superuser or self.user.is_system_auditor:
            return qs.all()
        ad_hoc_command_qs = self.user.get_queryset(AdHocCommand)
        host_qs = self.user.get_queryset(Host)
        return qs.filter(Q(host__isnull=True) | Q(host__in=host_qs), ad_hoc_command__in=ad_hoc_command_qs)

    def can_add(self, data):
        return False

    def can_change(self, obj, data):
        return False

    def can_delete(self, obj):
        return False
