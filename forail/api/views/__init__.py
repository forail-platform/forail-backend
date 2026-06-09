# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

import logging
import sys

from rest_framework.views import APIView

from forail.main.utils import camelcase_to_underscore

# Shared utilities re-exported from mixin
from forail.api.views.mixin import (  # noqa: F401
    api_exception_handler,
    unpartitioned_event_horizon,
    immutablesharedfields,
    redact_ansi,
    StdoutFilter,
    BadGateway,
    GatewayTimeout,
    HostRelatedSearchMixin,
    EnforceParentRelationshipMixin,
    UnifiedJobDeletionMixin,
    InstanceGroupMembershipMixin,
    RelatedJobsPreventDeleteMixin,
    OrganizationCountsMixin,
    NoTruncateMixin,
)

# Domain module re-exports
from forail.api.views.dashboard import *  # noqa: F401, F403
from forail.api.views.instances import *  # noqa: F401, F403
from forail.api.views.instance_groups import *  # noqa: F401, F403
from forail.api.views.schedules import *  # noqa: F401, F403
from forail.api.views.auth import *  # noqa: F401, F403
from forail.api.views.oauth import *  # noqa: F401, F403
from forail.api.views.users import *  # noqa: F401, F403
from forail.api.views.teams import *  # noqa: F401, F403
from forail.api.views.execution_environments import *  # noqa: F401, F403
from forail.api.views.projects import *  # noqa: F401, F403
from forail.api.views.credentials import *  # noqa: F401, F403
from forail.api.views.hosts import *  # noqa: F401, F403
from forail.api.views.groups import *  # noqa: F401, F403
from forail.api.views.inventory_sources import *  # noqa: F401, F403
from forail.api.views.job_templates import *  # noqa: F401, F403
from forail.api.views.jobs import *  # noqa: F401, F403
from forail.api.views.workflows import *  # noqa: F401, F403
from forail.api.views.workflow_approvals import *  # noqa: F401, F403
from forail.api.views.ad_hoc_commands import *  # noqa: F401, F403
from forail.api.views.system_jobs import *  # noqa: F401, F403
from forail.api.views.notifications import *  # noqa: F401, F403
from forail.api.views.activity_stream import *  # noqa: F401, F403
from forail.api.views.roles import *  # noqa: F401, F403
from forail.api.views.unified import *  # noqa: F401, F403


logger = logging.getLogger('forail.api.views')


# Create view functions for all of the class-based views to simplify inclusion
# in URL patterns and reverse URL lookups, converting CamelCase names to
# lowercase_with_underscore (e.g. MyView.as_view() becomes my_view).
this_module = sys.modules[__name__]
for attr, value in list(locals().items()):
    if isinstance(value, type) and issubclass(value, APIView):
        name = camelcase_to_underscore(attr)
        view = value.as_view()
        setattr(this_module, name, view)
