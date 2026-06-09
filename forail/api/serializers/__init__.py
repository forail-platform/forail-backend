# Copyright (c) 2015 Ansible, Inc.
# Copyright (c) 2026 Krstan Vjestica / Forail Project
# All Rights Reserved.

"""
Forail API Serializers Package.

This package contains all Django REST Framework serializers for the Forail API.
The serializers have been organized into modules by domain:

- base.py: Base serializer classes, utilities, and shared mixins
- unified.py: UnifiedJob and UnifiedJobTemplate serializers
- users.py: User serializers
- oauth.py: OAuth2 token and application serializers
- organizations.py: Organization, Team, and Role serializers
- projects.py: Project and ProjectUpdate serializers
- execution_environments.py: Execution Environment serializers
- inventory.py: Inventory, Host, Group, and InventorySource serializers
- credentials.py: Credential and CredentialType serializers
- jobs.py: JobTemplate, Job, AdHocCommand, SystemJob serializers
- workflows.py: WorkflowJobTemplate, WorkflowJob, and related serializers
- events.py: Job/Project/AdHoc/Inventory/System event serializers
- notifications.py: NotificationTemplate, Notification, Label serializers
- schedules.py: Schedule serializers
- instances.py: Instance, InstanceGroup, and HostMetric serializers
- activity_stream.py: ActivityStream serializer

All serializers are re-exported from this __init__.py for backward compatibility.
"""

# Re-export from base module
from forail.api.serializers.base import (
    # Constants
    DEFAULT_SUMMARY_FIELDS,
    SUMMARIZABLE_FK_FIELDS,
    CONSTRUCTED_INVENTORY_SOURCE_EDITABLE_FIELDS,
    # Helper functions
    reverse_gfk,
    role_summary_fields_generator,  # exported for tests that mock it
    # Base classes and mixins
    BaseSerializer,
    BaseSerializerMetaclass,
    BaseSerializerWithVariables,
    CopySerializer,
    EmptySerializer,
    LabelsListMixin,
    logger,
)

# Re-export from unified module
from forail.api.serializers.unified import (
    UnifiedJobTemplateSerializer,
    UnifiedJobSerializer,
    UnifiedJobListSerializer,
    UnifiedJobStdoutSerializer,
)

# Re-export from users module
from forail.api.serializers.users import (
    UserSerializer,
    UserActivityStreamSerializer,
)

# Re-export from oauth module
from forail.api.serializers.oauth import (
    BaseOAuth2TokenSerializer,
    UserAuthorizedTokenSerializer,
    OAuth2TokenSerializer,
    OAuth2TokenDetailSerializer,
    UserPersonalTokenSerializer,
    OAuth2ApplicationSerializer,
)

# Re-export from organizations module
from forail.api.serializers.organizations import (
    OrganizationSerializer,
    TeamSerializer,
    RoleSerializer,
    RoleSerializerWithParentAccess,
    ResourceAccessListElementSerializer,
)

# Re-export from projects module
from forail.api.serializers.projects import (
    ProjectOptionsSerializer,
    ProjectSerializer,
    ProjectPlaybooksSerializer,
    ProjectInventoriesSerializer,
    ProjectUpdateViewSerializer,
    ProjectUpdateSerializer,
    ProjectUpdateDetailSerializer,
    ProjectUpdateListSerializer,
    ProjectUpdateCancelSerializer,
)

# Re-export from execution_environments module
from forail.api.serializers.execution_environments import (
    ExecutionEnvironmentSerializer,
)

# Re-export from inventory module
from forail.api.serializers.inventory import (
    InventorySerializer,
    ConstructedFieldMixin,
    ConstructedCharField,
    ConstructedIntegerField,
    ConstructedInventorySerializer,
    InventoryScriptSerializer,
    HostSerializer,
    AnsibleFactsSerializer,
    GroupSerializer,
    BulkHostSerializer,
    BulkHostCreateSerializer,
    BulkHostDeleteSerializer,
    GroupTreeSerializer,
    BaseVariableDataSerializer,
    InventoryVariableDataSerializer,
    HostVariableDataSerializer,
    GroupVariableDataSerializer,
    InventorySourceOptionsSerializer,
    InventorySourceSerializer,
    InventorySourceUpdateSerializer,
    InventoryUpdateSerializer,
    InventoryUpdateDetailSerializer,
    InventoryUpdateListSerializer,
    InventoryUpdateCancelSerializer,
)

# Re-export from credentials module
from forail.api.serializers.credentials import (
    CredentialTypeSerializer,
    CredentialSerializer,
    CredentialSerializerCreate,
    CredentialInputSourceSerializer,
    UserCredentialSerializerCreate,
    TeamCredentialSerializerCreate,
    OrganizationCredentialSerializerCreate,
)

# Re-export from jobs module
from forail.api.serializers.jobs import (
    JobOptionsSerializer,
    JobTemplateMixin,
    JobTemplateSerializer,
    JobTemplateWithSpecSerializer,
    JobSerializer,
    JobDetailSerializer,
    JobCancelSerializer,
    JobRelaunchSerializer,
    JobCreateScheduleSerializer,
    JobListSerializer,
    JobHostSummarySerializer,
    JobLaunchSerializer,
    AdHocCommandSerializer,
    AdHocCommandDetailSerializer,
    AdHocCommandCancelSerializer,
    AdHocCommandRelaunchSerializer,
    AdHocCommandListSerializer,
    SystemJobTemplateSerializer,
    SystemJobSerializer,
    SystemJobCancelSerializer,
    SystemJobListSerializer,
)

# Re-export from workflows module
from forail.api.serializers.workflows import (
    WorkflowJobTemplateSerializer,
    WorkflowJobTemplateWithSpecSerializer,
    WorkflowJobSerializer,
    WorkflowJobListSerializer,
    WorkflowJobCancelSerializer,
    WorkflowApprovalViewSerializer,
    WorkflowApprovalSerializer,
    WorkflowApprovalActivityStreamSerializer,
    WorkflowApprovalListSerializer,
    WorkflowApprovalTemplateSerializer,
    LaunchConfigurationBaseSerializer,
    WorkflowJobTemplateNodeSerializer,
    WorkflowJobNodeSerializer,
    WorkflowJobNodeListSerializer,
    WorkflowJobNodeDetailSerializer,
    WorkflowJobTemplateNodeDetailSerializer,
    WorkflowJobTemplateNodeCreateApprovalSerializer,
    WorkflowJobLaunchSerializer,
    BulkJobNodeSerializer,
    BulkJobLaunchSerializer,
)

# Re-export from events module
from forail.api.serializers.events import (
    JobEventSerializer,
    ProjectUpdateEventSerializer,
    AdHocCommandEventSerializer,
    InventoryUpdateEventSerializer,
    SystemJobEventSerializer,
)

# Re-export from notifications module
from forail.api.serializers.notifications import (
    NotificationTemplateSerializer,
    NotificationSerializer,
    LabelSerializer,
)

# Re-export from schedules module
from forail.api.serializers.schedules import (
    SchedulePreviewSerializer,
    ScheduleSerializer,
)

# Re-export from instances module
from forail.api.serializers.instances import (
    InstanceLinkSerializer,
    InstanceNodeSerializer,
    ReceptorAddressSerializer,
    InstanceSerializer,
    InstanceHealthCheckSerializer,
    HostMetricSerializer,
    HostMetricSummaryMonthlySerializer,
    InstanceGroupSerializer,
)

# Re-export from activity_stream module
from forail.api.serializers.activity_stream import (
    ActivityStreamSerializer,
)

# Make all exports available
__all__ = [
    # Constants
    'DEFAULT_SUMMARY_FIELDS',
    'SUMMARIZABLE_FK_FIELDS',
    'CONSTRUCTED_INVENTORY_SOURCE_EDITABLE_FIELDS',
    # Helper functions
    'reverse_gfk',
    'role_summary_fields_generator',
    # Base classes
    'BaseSerializer',
    'BaseSerializerMetaclass',
    'BaseSerializerWithVariables',
    'CopySerializer',
    'EmptySerializer',
    'LabelsListMixin',
    'logger',
    # Unified serializers
    'UnifiedJobTemplateSerializer',
    'UnifiedJobSerializer',
    'UnifiedJobListSerializer',
    'UnifiedJobStdoutSerializer',
    # User serializers
    'UserSerializer',
    'UserActivityStreamSerializer',
    'BaseOAuth2TokenSerializer',
    'UserAuthorizedTokenSerializer',
    'OAuth2TokenSerializer',
    'OAuth2TokenDetailSerializer',
    'UserPersonalTokenSerializer',
    'OAuth2ApplicationSerializer',
    # Organization serializers
    'OrganizationSerializer',
    'TeamSerializer',
    'RoleSerializer',
    'RoleSerializerWithParentAccess',
    'ResourceAccessListElementSerializer',
    # Project serializers
    'ProjectOptionsSerializer',
    'ProjectSerializer',
    'ProjectPlaybooksSerializer',
    'ProjectInventoriesSerializer',
    'ProjectUpdateViewSerializer',
    'ProjectUpdateSerializer',
    'ProjectUpdateDetailSerializer',
    'ProjectUpdateListSerializer',
    'ProjectUpdateCancelSerializer',
    # Execution Environment serializers
    'ExecutionEnvironmentSerializer',
    # Inventory serializers
    'InventorySerializer',
    'ConstructedFieldMixin',
    'ConstructedCharField',
    'ConstructedIntegerField',
    'ConstructedInventorySerializer',
    'InventoryScriptSerializer',
    'HostSerializer',
    'AnsibleFactsSerializer',
    'GroupSerializer',
    'BulkHostSerializer',
    'BulkHostCreateSerializer',
    'BulkHostDeleteSerializer',
    'GroupTreeSerializer',
    'BaseVariableDataSerializer',
    'InventoryVariableDataSerializer',
    'HostVariableDataSerializer',
    'GroupVariableDataSerializer',
    'InventorySourceOptionsSerializer',
    'InventorySourceSerializer',
    'InventorySourceUpdateSerializer',
    'InventoryUpdateSerializer',
    'InventoryUpdateDetailSerializer',
    'InventoryUpdateListSerializer',
    'InventoryUpdateCancelSerializer',
    # Credential serializers
    'CredentialTypeSerializer',
    'CredentialSerializer',
    'CredentialSerializerCreate',
    'CredentialInputSourceSerializer',
    'UserCredentialSerializerCreate',
    'TeamCredentialSerializerCreate',
    'OrganizationCredentialSerializerCreate',
    # Job serializers
    'JobOptionsSerializer',
    'JobTemplateMixin',
    'JobTemplateSerializer',
    'JobTemplateWithSpecSerializer',
    'JobSerializer',
    'JobDetailSerializer',
    'JobCancelSerializer',
    'JobRelaunchSerializer',
    'JobCreateScheduleSerializer',
    'JobListSerializer',
    'JobHostSummarySerializer',
    'JobLaunchSerializer',
    # Ad Hoc Command serializers
    'AdHocCommandSerializer',
    'AdHocCommandDetailSerializer',
    'AdHocCommandCancelSerializer',
    'AdHocCommandRelaunchSerializer',
    'AdHocCommandListSerializer',
    # System Job serializers
    'SystemJobTemplateSerializer',
    'SystemJobSerializer',
    'SystemJobCancelSerializer',
    'SystemJobListSerializer',
    # Workflow serializers
    'WorkflowJobTemplateSerializer',
    'WorkflowJobTemplateWithSpecSerializer',
    'WorkflowJobSerializer',
    'WorkflowJobListSerializer',
    'WorkflowJobCancelSerializer',
    'WorkflowApprovalViewSerializer',
    'WorkflowApprovalSerializer',
    'WorkflowApprovalActivityStreamSerializer',
    'WorkflowApprovalListSerializer',
    'WorkflowApprovalTemplateSerializer',
    'LaunchConfigurationBaseSerializer',
    'WorkflowJobTemplateNodeSerializer',
    'WorkflowJobNodeSerializer',
    'WorkflowJobNodeListSerializer',
    'WorkflowJobNodeDetailSerializer',
    'WorkflowJobTemplateNodeDetailSerializer',
    'WorkflowJobTemplateNodeCreateApprovalSerializer',
    'WorkflowJobLaunchSerializer',
    'BulkJobNodeSerializer',
    'BulkJobLaunchSerializer',
    # Event serializers
    'JobEventSerializer',
    'ProjectUpdateEventSerializer',
    'AdHocCommandEventSerializer',
    'InventoryUpdateEventSerializer',
    'SystemJobEventSerializer',
    # Notification serializers
    'NotificationTemplateSerializer',
    'NotificationSerializer',
    'LabelSerializer',
    # Schedule serializers
    'SchedulePreviewSerializer',
    'ScheduleSerializer',
    # Instance serializers
    'InstanceLinkSerializer',
    'InstanceNodeSerializer',
    'ReceptorAddressSerializer',
    'InstanceSerializer',
    'InstanceHealthCheckSerializer',
    'HostMetricSerializer',
    'HostMetricSummaryMonthlySerializer',
    'InstanceGroupSerializer',
    # Activity Stream serializers
    'ActivityStreamSerializer',
]
