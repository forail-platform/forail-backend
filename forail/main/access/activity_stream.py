# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

from django.db.models import Q

from forail.main.access.base import BaseAccess
from forail.main.access.users import OAuth2ApplicationAccess, OAuth2TokenAccess
from forail.main.models import (
    ActivityStream,
    Credential,
    Inventory,
    JobTemplate,
    Organization,
    Project,
    Role,
    Team,
    WorkflowJobTemplate,
)


class ActivityStreamAccess(BaseAccess):
    """
    I can see activity stream events only when I have permission on all objects included in the event
    """

    model = ActivityStream
    prefetch_related = (
        'organization',
        'user',
        'inventory',
        'host',
        'group',
        'inventory_update',
        'credential',
        'credential_type',
        'team',
        'ad_hoc_command',
        'o_auth2_application',
        'o_auth2_access_token',
        'notification_template',
        'notification',
        'label',
        'role',
        'actor',
        'schedule',
        'unified_job_template',
        'workflow_job_template_node',
    )

    def filtered_queryset(self):
        """
        The full set is returned if the user is:
         - System Administrator
         - System Auditor
        These users will be able to see orphaned activity stream items
        (the related resource has been deleted), as well as the other
        obscure cases listed here

        Complex permissions omitted from the activity stream of a normal user:
         - host access via group
         - permissions (from prior versions)
         - notifications via team admin access

        Activity stream events that have been omitted from list for
        normal users since 2.4:
         - unified job templates
         - unified jobs
         - schedules
         - custom inventory scripts
        """
        qs = self.model.objects.all()
        # FIXME: the following fields will be attached to the wrong object
        # if they are included in prefetch_related because of
        # https://github.com/django-polymorphic/django-polymorphic/issues/68
        # 'job_template', 'job', 'project', 'project_update', 'workflow_job',
        # 'inventory_source', 'workflow_job_template'

        q = Q(user=self.user)
        inventory_set = Inventory.accessible_pk_qs(self.user, 'read_role')
        if inventory_set:
            q |= (
                Q(ad_hoc_command__inventory__in=inventory_set)
                | Q(inventory__in=inventory_set)
                | Q(host__inventory__in=inventory_set)
                | Q(group__inventory__in=inventory_set)
                | Q(inventory_source__inventory__in=inventory_set)
                | Q(inventory_update__inventory_source__inventory__in=inventory_set)
            )

        credential_set = Credential.accessible_pk_qs(self.user, 'read_role')
        if credential_set:
            q |= Q(credential__in=credential_set)

        auditing_orgs = (
            (Organization.accessible_objects(self.user, 'admin_role') | Organization.accessible_objects(self.user, 'auditor_role'))
            .distinct()
            .values_list('id', flat=True)
        )
        if auditing_orgs:
            q |= (
                Q(user__in=auditing_orgs.values('member_role__members'))
                | Q(organization__in=auditing_orgs)
                | Q(notification_template__organization__in=auditing_orgs)
                | Q(notification__notification_template__organization__in=auditing_orgs)
                | Q(label__organization__in=auditing_orgs)
                | Q(role__in=Role.visible_roles(self.user) if auditing_orgs else [])
            )

        project_set = Project.accessible_pk_qs(self.user, 'read_role')
        if project_set:
            q |= Q(project__in=project_set) | Q(project_update__project__in=project_set)

        jt_set = JobTemplate.accessible_pk_qs(self.user, 'read_role')
        if jt_set:
            q |= Q(job_template__in=jt_set) | Q(job__job_template__in=jt_set)

        wfjt_set = WorkflowJobTemplate.accessible_pk_qs(self.user, 'read_role')
        if wfjt_set:
            q |= (
                Q(workflow_job_template__in=wfjt_set)
                | Q(workflow_job_template_node__workflow_job_template__in=wfjt_set)
                | Q(workflow_job__workflow_job_template__in=wfjt_set)
            )

        team_set = Team.accessible_pk_qs(self.user, 'read_role')
        if team_set:
            q |= Q(team__in=team_set)

        app_set = OAuth2ApplicationAccess(self.user).filtered_queryset()
        if app_set:
            q |= Q(o_auth2_application__in=app_set)

        token_set = OAuth2TokenAccess(self.user).filtered_queryset()
        if token_set:
            q |= Q(o_auth2_access_token__in=token_set)

        return qs.filter(q).distinct()

    def can_add(self, data):
        return False

    def can_change(self, obj, data):
        return False

    def can_delete(self, obj):
        return False
