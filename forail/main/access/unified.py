# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

from django.db.models import Q, Prefetch

from forail.main.access.base import BaseAccess, access_registry
from forail.main.models import (
    Inventory,
    Label,
    Organization,
    UnifiedJob,
    UnifiedJobTemplate,
)


class UnifiedJobTemplateAccess(BaseAccess):
    """
    I can see a unified job template whenever I can see the same project,
    inventory source, WFJT, or job template.  Unified job templates do not include
    inventory sources without a cloud source.
    """

    model = UnifiedJobTemplate
    select_related = (
        'created_by',
        'modified_by',
        'next_schedule',
    )
    # prefetch last/current jobs so we get the real instance
    prefetch_related = (
        'last_job',
        'current_job',
        'organization',
        'credentials__credential_type',
        Prefetch('labels', queryset=Label.objects.all().order_by('name')),
    )

    # WISH - sure would be nice if the following worked, but it does not.
    # In the future, as django and polymorphic libs are upgraded, try again.

    # qs = qs.prefetch_related(
    #    'project',
    #    'inventory',
    # )

    def filtered_queryset(self):
        return self.model.objects.filter(
            Q(pk__in=self.model.accessible_pk_qs(self.user, 'read_role'))
            | Q(inventorysource__inventory__id__in=Inventory._accessible_pk_qs(Inventory, self.user, 'read_role'))
        )

    def can_start(self, obj, validate_license=True):
        access_class = access_registry[obj.__class__]
        access_instance = access_class(self.user)
        return access_instance.can_start(obj, validate_license=validate_license)

    def get_queryset(self):
        return super(UnifiedJobTemplateAccess, self).get_queryset().filter(workflowapprovaltemplate__isnull=True)


class UnifiedJobAccess(BaseAccess):
    """
    I can see a unified job whenever I can see the same project update,
    inventory update or job.
    """

    model = UnifiedJob
    prefetch_related = (
        'created_by',
        'modified_by',
        'organization',
        'unified_job_node__workflow_job',
        'unified_job_template',
        'instance_group',
        'credentials__credential_type',
        Prefetch('labels', queryset=Label.objects.all().order_by('name')),
    )

    # WISH - sure would be nice if the following worked, but it does not.
    # In the future, as django and polymorphic libs are upgraded, try again.

    # qs = qs.prefetch_related(
    #    'project',
    #    'inventory',
    #    'job_template',
    #    'inventory_source',
    #    'project___credential',
    #    'inventory_source___credential',
    #    'inventory_source___inventory',
    #    'job_template__inventory',
    #    'job_template__project',
    # )

    def filtered_queryset(self):
        inv_pk_qs = Inventory._accessible_pk_qs(Inventory, self.user, 'read_role')
        org_auditor_qs = Organization.objects.filter(Q(admin_role__members=self.user) | Q(auditor_role__members=self.user))
        qs = self.model.objects.filter(
            Q(unified_job_template_id__in=UnifiedJobTemplate.accessible_pk_qs(self.user, 'read_role'))
            | Q(inventoryupdate__inventory_source__inventory__id__in=inv_pk_qs)
            | Q(adhoccommand__inventory__id__in=inv_pk_qs)
            | Q(organization__in=org_auditor_qs)
        )
        return qs

    def get_queryset(self):
        return super(UnifiedJobAccess, self).get_queryset().filter(workflowapproval__isnull=True)
