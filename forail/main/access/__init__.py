# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

# Base utilities, classes, and decorators
from forail.main.access.base import (  # noqa: F401
    access_registry,
    BaseAccess,
    check_superuser,
    check_user_access,
    check_user_access_with_errors,
    get_object_from_data,
    get_object_or_400,
    get_user_capabilities,
    get_user_queryset,
    NotificationAttachMixin,
    register_access,
    UnifiedCredentialsMixin,
    vars_are_encrypted,
)

# Domain modules
from forail.main.access.instances import (  # noqa: F401
    InstanceAccess,
    InstanceGroupAccess,
    ReceptorAddressAccess,
)

from forail.main.access.users import (  # noqa: F401
    UserAccess,
    OAuth2ApplicationAccess,
    OAuth2TokenAccess,
)

from forail.main.access.organizations import (  # noqa: F401
    OrganizationAccess,
    TeamAccess,
)

from forail.main.access.inventory import (  # noqa: F401
    InventoryAccess,
    HostAccess,
    GroupAccess,
    InventorySourceAccess,
    InventoryUpdateAccess,
)

from forail.main.access.credentials import (  # noqa: F401
    CredentialTypeAccess,
    CredentialAccess,
    CredentialInputSourceAccess,
)

from forail.main.access.projects import (  # noqa: F401
    ExecutionEnvironmentAccess,
    ProjectAccess,
    ProjectUpdateAccess,
)

from forail.main.access.jobs import (  # noqa: F401
    JobTemplateAccess,
    JobAccess,
    SystemJobTemplateAccess,
    SystemJobAccess,
    JobLaunchConfigAccess,
    AdHocCommandAccess,
    AdHocCommandEventAccess,
)

from forail.main.access.workflows import (  # noqa: F401
    WorkflowJobTemplateNodeAccess,
    WorkflowJobNodeAccess,
    WorkflowJobTemplateAccess,
    WorkflowJobAccess,
    WorkflowApprovalAccess,
    WorkflowApprovalTemplateAccess,
)

from forail.main.access.events import (  # noqa: F401
    JobHostSummaryAccess,
    JobEventAccess,
    UnpartitionedJobEventAccess,
    ProjectUpdateEventAccess,
    InventoryUpdateEventAccess,
    SystemJobEventAccess,
)

from forail.main.access.notifications import (  # noqa: F401
    NotificationTemplateAccess,
    NotificationAccess,
    LabelAccess,
)

from forail.main.access.unified import (  # noqa: F401
    UnifiedJobTemplateAccess,
    UnifiedJobAccess,
)

from forail.main.access.schedules import ScheduleAccess  # noqa: F401

from forail.main.access.activity_stream import ActivityStreamAccess  # noqa: F401

from forail.main.access.roles import RoleAccess  # noqa: F401

# Maintain original __all__
__all__ = [
    'get_user_queryset',
    'check_user_access',
    'check_user_access_with_errors',
    'consumer_access',
]

# Auto-register all Access subclasses
from forail.main.models import UnpartitionedJobEvent  # noqa: E402

for cls in BaseAccess.__subclasses__():
    if cls.model is not None:
        access_registry[cls.model] = cls
access_registry[UnpartitionedJobEvent] = UnpartitionedJobEventAccess


def consumer_access(group_name):
    """
    consumer_access returns the proper Access class based on group_name
    for a channels consumer.
    """
    class_map = {'job_events': JobAccess, 'workflow_events': WorkflowJobAccess, 'ad_hoc_command_events': AdHocCommandAccess}
    return class_map.get(group_name)


def optimize_queryset(queryset):
    """
    A utility method in case you already have a queryset and just want to
    apply the standard optimizations for that model.
    In other words, use if you do not want to start from filtered_queryset for some reason.
    """
    if not queryset.model or queryset.model not in access_registry:
        return queryset
    access_class = access_registry[queryset.model]
    if access_class.select_related:
        queryset = queryset.select_related(*access_class.select_related)
    if access_class.prefetch_related:
        queryset = queryset.prefetch_related(*access_class.prefetch_related)
    return queryset
