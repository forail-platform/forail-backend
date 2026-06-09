# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

# Cloud provider inventory plugin settings

INV_ENV_VARIABLE_BLOCKED = ("HOME", "USER", "_", "TERM", "PATH")

# ----------------
# -- Amazon EC2 --
# ----------------
EC2_ENABLED_VAR = 'ec2_state'
EC2_ENABLED_VALUE = 'running'
EC2_INSTANCE_ID_VAR = 'instance_id'
EC2_EXCLUDE_EMPTY_GROUPS = True

# ------------
# -- VMware --
# ------------
VMWARE_ENABLED_VAR = 'guest.gueststate'
VMWARE_ENABLED_VALUE = 'running'
VMWARE_INSTANCE_ID_VAR = 'config.instanceUuid, config.instanceuuid'
VMWARE_EXCLUDE_EMPTY_GROUPS = True

VMWARE_VALIDATE_CERTS = False

# ---------------------------
# -- Google Compute Engine --
# ---------------------------
GCE_ENABLED_VAR = 'status'
GCE_ENABLED_VALUE = 'running'
GCE_EXCLUDE_EMPTY_GROUPS = True
GCE_INSTANCE_ID_VAR = 'gce_id'

# --------------------------------------
# -- Microsoft Azure Resource Manager --
# --------------------------------------
AZURE_RM_ENABLED_VAR = 'powerstate'
AZURE_RM_ENABLED_VALUE = 'running'
AZURE_RM_INSTANCE_ID_VAR = 'id'
AZURE_RM_EXCLUDE_EMPTY_GROUPS = True

# ---------------------
# ----- OpenStack -----
# ---------------------
OPENSTACK_ENABLED_VAR = 'status'
OPENSTACK_ENABLED_VALUE = 'ACTIVE'
OPENSTACK_EXCLUDE_EMPTY_GROUPS = True
OPENSTACK_INSTANCE_ID_VAR = 'openstack.id'

# ---------------------
# ----- oVirt4 -----
# ---------------------
RHV_ENABLED_VAR = 'status'
RHV_ENABLED_VALUE = 'up'
RHV_EXCLUDE_EMPTY_GROUPS = True
RHV_INSTANCE_ID_VAR = 'id'

# ---------------------
# ----- Controller     -----
# ---------------------
CONTROLLER_ENABLED_VAR = 'remote_tower_enabled'
CONTROLLER_ENABLED_VALUE = 'true'
CONTROLLER_EXCLUDE_EMPTY_GROUPS = True
CONTROLLER_INSTANCE_ID_VAR = 'remote_tower_id'

# ---------------------
# ----- Foreman -----
# ---------------------
SATELLITE6_ENABLED_VAR = 'foreman_enabled,foreman.enabled'
SATELLITE6_ENABLED_VALUE = 'True'
SATELLITE6_EXCLUDE_EMPTY_GROUPS = True
SATELLITE6_INSTANCE_ID_VAR = 'foreman_id,foreman.id'
# SATELLITE6_GROUP_PREFIX and SATELLITE6_GROUP_PATTERNS defined in source vars

# ----------------
# -- Red Hat Insights --
# ----------------
# INSIGHTS_ENABLED_VAR =
# INSIGHTS_ENABLED_VALUE =
INSIGHTS_INSTANCE_ID_VAR = 'insights_id'
INSIGHTS_EXCLUDE_EMPTY_GROUPS = False

# ----------------
# -- Terraform State --
# ----------------
# TERRAFORM_ENABLED_VAR =
# TERRAFORM_ENABLED_VALUE =
TERRAFORM_INSTANCE_ID_VAR = 'id'
TERRAFORM_EXCLUDE_EMPTY_GROUPS = True

# ------------------------
# OpenShift Virtualization
# ------------------------
OPENSHIFT_VIRTUALIZATION_EXCLUDE_EMPTY_GROUPS = True

# ---------------------
# ----- Custom -----
# ---------------------
# CUSTOM_ENABLED_VAR =
# CUSTOM_ENABLED_VALUE =
CUSTOM_EXCLUDE_EMPTY_GROUPS = False
# CUSTOM_INSTANCE_ID_VAR =

# ---------------------
# ----- SCM -----
# ---------------------
# SCM_ENABLED_VAR =
# SCM_ENABLED_VALUE =
SCM_EXCLUDE_EMPTY_GROUPS = False
# SCM_INSTANCE_ID_VAR =

# ----------------
# -- Constructed --
# ----------------
CONSTRUCTED_INSTANCE_ID_VAR = 'remote_tower_id'

CONSTRUCTED_EXCLUDE_EMPTY_GROUPS = False
