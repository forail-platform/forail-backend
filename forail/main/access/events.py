# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

from django.db.models import Q

from forail.main.access.base import BaseAccess
from forail.main.models import (
    Inventory,
    InventoryUpdateEvent,
    Job,
    JobEvent,
    JobHostSummary,
    JobTemplate,
    Host,
    Project,
    ProjectUpdateEvent,
    SystemJobEvent,
    UnpartitionedJobEvent,
)


class JobHostSummaryAccess(BaseAccess):
    """
    I can see job/host summary records whenever I can read both job and host.
    """

    model = JobHostSummary
    select_related = (
        'job',
        'job__job_template',
        'host',
    )

    def filtered_queryset(self):
        job_qs = self.user.get_queryset(Job)
        host_qs = self.user.get_queryset(Host)
        return self.model.objects.filter(job__in=job_qs, host__in=host_qs)

    def can_add(self, data):
        return False

    def can_change(self, obj, data):
        return False

    def can_delete(self, obj):
        return False


class JobEventAccess(BaseAccess):
    """
    I can see job event records whenever I can read both job and host.
    """

    model = JobEvent
    prefetch_related = (
        'job__job_template',
        'host',
    )

    def filtered_queryset(self):
        return self.model.objects.filter(
            Q(host__inventory__in=Inventory.accessible_pk_qs(self.user, 'read_role'))
            | Q(job__job_template__in=JobTemplate.accessible_pk_qs(self.user, 'read_role'))
        )

    def can_add(self, data):
        return False

    def can_change(self, obj, data):
        return False

    def can_delete(self, obj):
        return False


class UnpartitionedJobEventAccess(JobEventAccess):
    model = UnpartitionedJobEvent


class ProjectUpdateEventAccess(BaseAccess):
    """
    I can see project update event records whenever I can access the project update
    """

    model = ProjectUpdateEvent

    def filtered_queryset(self):
        return self.model.objects.filter(Q(project_update__project__in=Project.accessible_pk_qs(self.user, 'read_role')))

    def can_add(self, data):
        return False

    def can_change(self, obj, data):
        return False

    def can_delete(self, obj):
        return False


class InventoryUpdateEventAccess(BaseAccess):
    """
    I can see inventory update event records whenever I can access the inventory update
    """

    model = InventoryUpdateEvent

    def filtered_queryset(self):
        return self.model.objects.filter(Q(inventory_update__inventory_source__inventory__in=Inventory.accessible_pk_qs(self.user, 'read_role')))

    def can_add(self, data):
        return False

    def can_change(self, obj, data):
        return False

    def can_delete(self, obj):
        return False


class SystemJobEventAccess(BaseAccess):
    """
    I can only see manage System Jobs events if I'm a super user
    """

    model = SystemJobEvent

    def can_add(self, data):
        return False

    def can_change(self, obj, data):
        return False

    def can_delete(self, obj):
        return False
