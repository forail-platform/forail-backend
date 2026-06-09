# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from rest_framework.exceptions import PermissionDenied

from forail.main.access.base import (
    BaseAccess,
    NotificationAttachMixin,
    UnifiedCredentialsMixin,
    check_superuser,
    vars_are_encrypted,
)
from forail.main.access.jobs import JobLaunchConfigAccess
from forail.main.models import (
    ExecutionEnvironment,
    Inventory,
    Organization,
    UnifiedJobTemplate,
    WorkflowApproval,
    WorkflowApprovalTemplate,
    WorkflowJob,
    WorkflowJobNode,
    WorkflowJobTemplate,
    WorkflowJobTemplateNode,
)


class WorkflowJobTemplateNodeAccess(UnifiedCredentialsMixin, BaseAccess):
    """
    I can see/use a WorkflowJobTemplateNode if I have read permission
        to associated Workflow Job Template

    In order to add a node, I need:
     - admin access to parent WFJT
     - execute access to the unified job template being used
     - access prompted fields via. launch config access

    In order to do anything to a node, I need admin access to its WFJT

    In order to edit fields on a node, I need:
     - execute access to the unified job template of the node
     - access to prompted fields

    In order to delete a node, I only need the admin access its WFJT

    In order to manage connections (edges) between nodes I do not need anything
      beyond the standard admin access to its WFJT
    """

    model = WorkflowJobTemplateNode
    prefetch_related = ('success_nodes', 'failure_nodes', 'always_nodes', 'unified_job_template', 'workflow_job_template')

    def filtered_queryset(self):
        return self.model.objects.filter(workflow_job_template__in=WorkflowJobTemplate.accessible_objects(self.user, 'read_role'))

    @check_superuser
    def can_add(self, data):
        if not data:  # So the browseable API will work
            return True
        return (
            self.check_related('workflow_job_template', WorkflowJobTemplate, data, mandatory=True)
            and self.check_related('unified_job_template', UnifiedJobTemplate, data, role_field='execute_role')
            and self.check_related('inventory', Inventory, data, role_field='use_role')
            and self.check_related('execution_environment', ExecutionEnvironment, data, role_field='read_role')
        )

    def wfjt_admin(self, obj):
        if not obj.workflow_job_template:
            return self.user.is_superuser
        else:
            return self.user in obj.workflow_job_template.admin_role

    def ujt_execute(self, obj, data=None):
        if not obj.unified_job_template:
            return True
        return self.check_related('unified_job_template', UnifiedJobTemplate, data, obj=obj, role_field='execute_role', mandatory=True)

    def can_change(self, obj, data):
        # should not be able to edit the prompts if lacking access to UJT or WFJT
        return self.ujt_execute(obj, data=data) and self.wfjt_admin(obj) and JobLaunchConfigAccess(self.user).can_change(obj, data)

    def can_delete(self, obj):
        return self.wfjt_admin(obj)

    def check_same_WFJT(self, obj, sub_obj):
        if type(obj) != self.model or type(sub_obj) != self.model:
            raise Exception('Attaching workflow nodes only allowed for other nodes')
        if obj.workflow_job_template != sub_obj.workflow_job_template:
            return False
        return True

    def can_attach(self, obj, sub_obj, relationship, data, skip_sub_obj_read_check=False):
        if relationship in ('success_nodes', 'failure_nodes', 'always_nodes'):
            return self.wfjt_admin(obj) and self.check_same_WFJT(obj, sub_obj)
        return super().can_attach(obj, sub_obj, relationship, data, skip_sub_obj_read_check=skip_sub_obj_read_check)

    def can_unattach(self, obj, sub_obj, relationship, data=None):
        if relationship in ('success_nodes', 'failure_nodes', 'always_nodes'):
            return self.wfjt_admin(obj)
        return super().can_unattach(obj, sub_obj, relationship, data=None)


class WorkflowJobNodeAccess(BaseAccess):
    """
    I can see a WorkflowJobNode if I have permission to...
    the workflow job template associated with...
    the workflow job associated with the node.

    Any deletion of editing of individual nodes would undermine the integrity
    of the graph structure.
    Deletion must happen as a cascade delete from the workflow job.
    """

    model = WorkflowJobNode
    prefetch_related = (
        'unified_job_template',
        'job',
        'workflow_job',
        'credentials',
        'success_nodes',
        'failure_nodes',
        'always_nodes',
    )

    def filtered_queryset(self):
        return self.model.objects.filter(
            Q(workflow_job__unified_job_template__in=UnifiedJobTemplate.accessible_pk_qs(self.user, 'read_role'))
            | Q(workflow_job__organization__in=Organization.objects.filter(Q(admin_role__members=self.user)))
        )

    def can_read(self, obj):
        """Overriding this opens up detail view access for bulk jobs, where the workflow job has no associated workflow job template."""
        if obj.workflow_job.is_bulk_job and obj.workflow_job.created_by_id == self.user.id:
            return True
        return super().can_read(obj)

    @check_superuser
    def can_add(self, data):
        if data is None:  # Hide direct creation in API browser
            return False
        return self.check_related('unified_job_template', UnifiedJobTemplate, data, role_field='execute_role') and JobLaunchConfigAccess(self.user).can_add(
            data
        )

    def can_change(self, obj, data):
        return False

    def can_delete(self, obj):
        return False


# TODO: notification attachments?
class WorkflowJobTemplateAccess(NotificationAttachMixin, BaseAccess):
    """
    I can see/manage Workflow Job Templates based on object roles
    """

    model = WorkflowJobTemplate
    select_related = (
        'created_by',
        'modified_by',
        'organization',
        'next_schedule',
        'admin_role',
        'execute_role',
        'read_role',
    )

    def filtered_queryset(self):
        return self.model.accessible_objects(self.user, 'read_role')

    @check_superuser
    def can_add(self, data):
        """
        a user can create a job template if they are a superuser, an org admin
        of any org that the project is a member, or if they have user or team
        based permissions tying the project to the inventory source for the
        given action as well as the 'create' deploy permission.
        Users who are able to create deploy jobs can also run normal and check (dry run) jobs.
        """
        if not data:  # So the browseable API will work
            return Organization.accessible_objects(self.user, 'workflow_admin_role').exists()

        if not self.check_related('organization', Organization, data, role_field='workflow_admin_role', mandatory=True):
            if data.get('organization', None) is None:
                self.messages['organization'] = [_('An organization is required to create a workflow job template for normal user')]
            return False

        if not self.check_related('inventory', Inventory, data, role_field='use_role'):
            self.messages['inventory'] = [_('You do not have use_role to the inventory')]
            return False

        if not self.check_related('execution_environment', ExecutionEnvironment, data, role_field='read_role'):
            self.messages['execution_environment'] = [_('You do not have read_role to the execution environment')]
            return False

        return True

    def can_copy(self, obj):
        if self.save_messages:
            missing_ujt = []
            missing_credentials = []
            missing_inventories = []
            qs = obj.workflow_job_template_nodes
            qs = qs.prefetch_related('unified_job_template', 'inventory__use_role', 'credentials__use_role')
            for node in qs.all():
                if node.inventory and self.user not in node.inventory.use_role:
                    missing_inventories.append(node.inventory.name)
                for cred in node.credentials.all():
                    if self.user not in cred.use_role:
                        missing_credentials.append(cred.name)
                ujt = node.unified_job_template
                if ujt and not self.user.can_access(UnifiedJobTemplate, 'start', ujt, validate_license=False):
                    missing_ujt.append(ujt.name)
            if missing_ujt:
                self.messages['templates_unable_to_copy'] = missing_ujt
            if missing_credentials:
                self.messages['credentials_unable_to_copy'] = missing_credentials
            if missing_inventories:
                self.messages['inventories_unable_to_copy'] = missing_inventories

        return self.check_related('organization', Organization, {'reference_obj': obj}, role_field='workflow_admin_role', mandatory=True)

    def can_start(self, obj, validate_license=True):
        if validate_license:
            # check basic license, node count
            self.check_license()

            # Check the per-org limit
            self.check_org_host_limit({'inventory': obj.inventory})

        # Super users can start any job
        if self.user.is_superuser:
            return True

        return self.user in obj.execute_role

    def can_change(self, obj, data):
        if self.user.is_superuser:
            return True

        return (
            self.check_related('organization', Organization, data, role_field='workflow_admin_role', obj=obj)
            and self.check_related('inventory', Inventory, data, role_field='use_role', obj=obj)
            and self.check_related('execution_environment', ExecutionEnvironment, data, obj=obj, role_field='read_role')
            and self.user in obj.admin_role
        )

    def can_delete(self, obj):
        return self.user.is_superuser or self.user in obj.admin_role


class WorkflowJobAccess(BaseAccess):
    """
    I can only see Workflow Jobs if I can see the associated
    workflow job template that it was created from.
    I can delete them if I am admin of their workflow job template
    I can cancel one if I can delete it
       I can also cancel it if I started it
    """

    model = WorkflowJob
    select_related = (
        'created_by',
        'modified_by',
        'organization',
    )

    def filtered_queryset(self):
        return WorkflowJob.objects.filter(
            Q(unified_job_template__in=UnifiedJobTemplate.accessible_pk_qs(self.user, 'read_role'))
            | Q(organization__in=Organization.objects.filter(Q(admin_role__members=self.user)), is_bulk_job=True)
        )

    def can_read(self, obj):
        """Overriding this opens up detail view access for bulk jobs, where the workflow job has no associated workflow job template."""
        if obj.is_bulk_job and obj.created_by_id == self.user.id:
            return True
        return super().can_read(obj)

    def can_add(self, data):
        # Old add-start system for launching jobs is being depreciated, and
        # not supported for new types of resources
        return False

    def can_change(self, obj, data):
        return False

    @check_superuser
    def can_delete(self, obj):
        return obj.workflow_job_template and obj.workflow_job_template.organization and self.user in obj.workflow_job_template.organization.workflow_admin_role

    def get_method_capability(self, method, obj, parent_obj):
        if method == 'start':
            # Return simplistic permission, will perform detailed check on POST
            if not obj.workflow_job_template:
                return self.user.is_superuser
            return self.user in obj.workflow_job_template.execute_role
        return super(WorkflowJobAccess, self).get_method_capability(method, obj, parent_obj)

    def can_start(self, obj, validate_license=True):
        if validate_license:
            self.check_license()

            # Check the per-org limit
            self.check_org_host_limit({'inventory': obj.inventory})

        if self.user.is_superuser:
            return True

        template = obj.workflow_job_template
        if not template and obj.job_template_id:
            template = obj.job_template
        # only superusers can relaunch orphans
        if not template:
            return False

        # Obtain prompts used to start original job
        JobLaunchConfig = obj._meta.get_field('launch_config').related_model
        try:
            config = JobLaunchConfig.objects.get(job=obj)
        except JobLaunchConfig.DoesNotExist:
            if self.save_messages:
                self.messages['detail'] = _('Workflow Job was launched with unknown prompts.')
            return False

        # execute permission to WFJT is mandatory for any relaunch
        if self.user not in template.execute_role:
            return False

        # Check if access to prompts to prevent relaunch
        if config.prompts_dict():
            if obj.created_by_id != self.user.pk and vars_are_encrypted(config.extra_data):
                raise PermissionDenied(_("Job was launched with secret prompts provided by another user."))
            if not JobLaunchConfigAccess(self.user).can_add({'reference_obj': config}):
                raise PermissionDenied(_('Job was launched with prompts you lack access to.'))
            if config.has_unprompted(template):
                raise PermissionDenied(_('Job was launched with prompts no longer accepted.'))

        return True  # passed config checks

    def can_recreate(self, obj):
        node_qs = obj.workflow_job_nodes.all().prefetch_related('inventory', 'credentials', 'unified_job_template')
        node_access = WorkflowJobNodeAccess(user=self.user)
        wj_add_perm = True
        for node in node_qs:
            if not node_access.can_add({'reference_obj': node}):
                wj_add_perm = False
        if not wj_add_perm and self.save_messages:
            self.messages['workflow_job_template'] = _('You do not have permission to the workflow job resources required for relaunch.')
        return wj_add_perm

    def can_cancel(self, obj):
        if not obj.can_cancel:
            return False
        if self.user == obj.created_by or self.can_delete(obj):
            return True
        return obj.workflow_job_template is not None and self.user in obj.workflow_job_template.admin_role


class WorkflowApprovalAccess(BaseAccess):
    """
    A user can create a workflow approval if they are a superuser, an org admin
    of the org connected to the workflow, or if they are assigned as admins to
    the workflow.

    A user can approve a workflow when they are:
    - a superuser
    - a workflow admin
    - an organization admin
    - any user who has explicitly been assigned the "approver" role

    A user can see approvals if they have read access to the associated WorkflowJobTemplate.
    """

    model = WorkflowApproval
    prefetch_related = (
        'created_by',
        'modified_by',
    )

    def can_use(self, obj):
        return True

    def can_start(self, obj, validate_license=True):
        return True

    def filtered_queryset(self):
        return self.model.objects.filter(unified_job_node__workflow_job__unified_job_template__in=WorkflowJobTemplate.accessible_pk_qs(self.user, 'read_role'))

    def can_approve_or_deny(self, obj):
        if (obj.workflow_job_template and self.user in obj.workflow_job_template.approval_role) or self.user.is_superuser:
            return True


class WorkflowApprovalTemplateAccess(BaseAccess):
    """
    A user can create a workflow approval if they are a superuser, an org admin
    of the org connected to the workflow, or if they are assigned as admins to
    the workflow.

    A user can approve a workflow when they are:
    - a superuser
    - a workflow admin
    - an organization admin
    - any user who has explicitly been assigned the "approver" role at the workflow or organization level

    A user can see approval templates if they have read access to the associated WorkflowJobTemplate.
    """

    model = WorkflowApprovalTemplate
    prefetch_related = (
        'created_by',
        'modified_by',
    )

    @check_superuser
    def can_add(self, data):
        if data is None:  # Hide direct creation in API browser
            return False
        else:
            return self.check_related('workflow_approval_template', UnifiedJobTemplate, role_field='admin_role')

    def can_change(self, obj, data):
        return self.user.can_access(WorkflowJobTemplate, 'change', obj.workflow_job_template, data={})

    def can_start(self, obj, validate_license=False):
        # for copying WFJTs that contain approval nodes
        if self.user.is_superuser:
            return True

        return self.user in obj.workflow_job_template.execute_role

    def filtered_queryset(self):
        return self.model.objects.filter(workflowjobtemplatenodes__workflow_job_template__in=WorkflowJobTemplate.accessible_pk_qs(self.user, 'read_role'))
