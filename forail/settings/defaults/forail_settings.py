# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

# Forail-specific miscellaneous settings

# ---------------------
# -- Activity Stream --
# ---------------------
# Defaults for enabling/disabling activity stream.
# Note: These settings may be overridden by database settings.
ACTIVITY_STREAM_ENABLED = True
ACTIVITY_STREAM_ENABLED_FOR_INVENTORY_SYNC = False

# Note: This setting may be overridden by database settings.
ORG_ADMINS_CAN_SEE_ALL_USERS = True
MANAGE_ORGANIZATION_AUTH = True
DISABLE_LOCAL_AUTH = False

# Note: This setting may be overridden by database settings.
TOWER_URL_BASE = "https://towerhost"

INSIGHTS_URL_BASE = "https://example.org"
INSIGHTS_AGENT_MIME = 'application/example'
# See https://github.com/ansible/awx-facts-playbooks
INSIGHTS_SYSTEM_ID_FILE = '/etc/redhat-access-insights/machine-id'
INSIGHTS_CERT_PATH = "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem"

# Automatically remove nodes that have missed their heartbeats after some time
AWX_AUTO_DEPROVISION_INSTANCES = False

# If False, do not allow creation of resources that are shared with the platform ingress
# e.g. organizations, teams, and users
ALLOW_LOCAL_RESOURCE_MANAGEMENT = True

# Enable Pendo on the UI, possible values are 'off', 'anonymous', and 'detailed'
# Note: This setting may be overridden by database settings.
PENDO_TRACKING_STATE = "off"

# Enables Insights data collection.
# Note: This setting may be overridden by database settings.
INSIGHTS_TRACKING_STATE = False

# Last gather date for Analytics
AUTOMATION_ANALYTICS_LAST_GATHER = None
# Last gathered entries for expensive Analytics
AUTOMATION_ANALYTICS_LAST_ENTRIES = ''

# Use middleware to get request statistics
AWX_REQUEST_PROFILE = False

#
# Optionally, AWX can generate DOT graphs
# (http://www.graphviz.org/doc/info/lang.html) for per-request profiling
# via gprof2dot (https://github.com/jrfonseca/gprof2dot)
#
# If you set this to True, you must `/var/lib/awx/venv/awx/bin/pip install gprof2dot`
# .dot files will be saved in `/var/log/tower/profile/` and can be converted e.g.,
#
# ~ yum install graphviz
# ~ dot -o profile.png -Tpng /var/log/tower/profile/some-profile-data.dot
#
AWX_REQUEST_PROFILE_WITH_DOT = False

# Allow profiling callback workers via SIGUSR1
AWX_CALLBACK_PROFILE = False

# Delete temporary directories created to store playbook run-time
AWX_CLEANUP_PATHS = True

# Allow ansible-runner to store env folder (may contain sensitive information)
AWX_RUNNER_OMIT_ENV_FILES = True

# Allow ansible-runner to save ansible output
# (changing to False may cause performance issues)
AWX_RUNNER_SUPPRESS_OUTPUT_FILE = True

# https://github.com/ansible/ansible-runner/pull/1191/files
# Interval in seconds between the last message and keep-alive messages that
# ansible-runner will send
AWX_RUNNER_KEEPALIVE_SECONDS = 0

# Delete completed work units in receptor
RECEPTOR_RELEASE_WORK = True

# K8S only. Use receptor_log_level on AWX spec to set this properly
RECEPTOR_LOG_LEVEL = 'info'

# Name of the default task queue
DEFAULT_EXECUTION_QUEUE_NAME = 'default'
# pod spec used when the default execution queue is a container group, e.g. when deploying on k8s/ocp with the operator
DEFAULT_EXECUTION_QUEUE_POD_SPEC_OVERRIDE = ''
# Max number of concurrently consumed forks for the default execution queue
# Zero means no limit
DEFAULT_EXECUTION_QUEUE_MAX_FORKS = 0
# Max number of concurrently running jobs for the default execution queue
# Zero means no limit
DEFAULT_EXECUTION_QUEUE_MAX_CONCURRENT_JOBS = 0

# Name of the default controlplane queue
DEFAULT_CONTROL_PLANE_QUEUE_NAME = 'controlplane'

# Extend container runtime attributes.
# For example, to disable SELinux in containers for podman
# DEFAULT_CONTAINER_RUN_OPTIONS = ['--security-opt', 'label=disable']
DEFAULT_CONTAINER_RUN_OPTIONS = ['--network', 'slirp4netns:enable_ipv6=true']

# Mount exposed paths as hostPath resource in k8s/ocp
AWX_MOUNT_ISOLATED_PATHS_ON_K8S = False

# License compliance for total host count. Possible values:
# - '': No model - Subscription not counted from Host Metrics
# - 'unique_managed_hosts': Compliant = automated - deleted hosts (using /api/v2/host_metrics/)
SUBSCRIPTION_USAGE_MODEL = ''

# Host metrics cleanup - last time of the task/command run
CLEANUP_HOST_METRICS_LAST_TS = None
# Host metrics cleanup - minimal interval between two cleanups in days
CLEANUP_HOST_METRICS_INTERVAL = 30  # days
# Host metrics cleanup - soft-delete HostMetric records with last_automation < [threshold] (in months)
CLEANUP_HOST_METRICS_SOFT_THRESHOLD = 12  # months
# Host metrics cleanup
# - delete HostMetric record with deleted=True and last_deleted < [threshold]
# - also threshold for computing HostMetricSummaryMonthly (command/scheduled task)
CLEANUP_HOST_METRICS_HARD_THRESHOLD = 36  # months

# Host metric summary monthly task - last time of run
HOST_METRIC_SUMMARY_TASK_LAST_TS = None
HOST_METRIC_SUMMARY_TASK_INTERVAL = 7  # days


# TODO: cmeyers, replace with with register pattern
# The register pattern is particularly nice for this because we need
# to know the process to start the thread that will be the server.
# The registration location should be the same location as we would
# call MetricsServer.start()
# TODO: cmeyers, break this out into a separate django app so other
# projects can take advantage.

METRICS_SERVICE_CALLBACK_RECEIVER = 'callback_receiver'
METRICS_SERVICE_DISPATCHER = 'dispatcher'
METRICS_SERVICE_WEBSOCKETS = 'websockets'

METRICS_SUBSYSTEM_CONFIG = {
    'server': {
        METRICS_SERVICE_CALLBACK_RECEIVER: {
            'port': 8014,
        },
        METRICS_SERVICE_DISPATCHER: {
            'port': 8015,
        },
        METRICS_SERVICE_WEBSOCKETS: {
            'port': 8016,
        },
    }
}
