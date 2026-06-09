# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

# Job execution, events, ansible configuration

import tempfile


# Warning: this is a placeholder for a database setting
# This should not be set via a file.
DEFAULT_EXECUTION_ENVIRONMENT = None

# This list is used for creating default EEs when running awx-manage create_preload_data.
# Should be ordered from highest to lowest precedence.
# The awx-manage register_default_execution_environments command reads this setting and registers the EE(s)
# If a registry credential is needed to pull the image, that can be provided to the awx-manage command
GLOBAL_JOB_EXECUTION_ENVIRONMENTS = [{'name': 'AWX EE (latest)', 'image': 'quay.io/ansible/awx-ee:latest'}]
# This setting controls which EE will be used for project updates.
# The awx-manage register_default_execution_environments command reads this setting and registers the EE
# This image is distinguished from others by having "managed" set to True and users have limited
# ability to modify it through the API.
# If a registry credential is needed to pull the image, that can be provided to the awx-manage command
CONTROL_PLANE_EXECUTION_ENVIRONMENT = 'quay.io/ansible/awx-ee:latest'

# Note: This setting may be overridden by database settings.
STDOUT_MAX_BYTES_DISPLAY = 1048576

# Returned in the header on event api lists as a recommendation to the UI
# on how many events to display before truncating/hiding
MAX_UI_JOB_EVENTS = 4000

# Returned in index.html, tells the UI if it should make requests
# to update job data in response to status changes websocket events
UI_LIVE_UPDATES_ENABLED = True

# The maximum size of the ansible callback event's res data structure
# beyond this limit and the value will be removed
MAX_EVENT_RES_DATA = 700000

# Note: These settings may be overridden by database settings.
EVENT_STDOUT_MAX_BYTES_DISPLAY = 1024
MAX_WEBSOCKET_EVENT_RATE = 30

# The amount of time before a stdout file is expired and removed locally
# Note that this can be recreated if the stdout is downloaded
LOCAL_STDOUT_EXPIRE_TIME = 2592000

# The number of processes spawned by the callback receiver to process job
# events into the database
JOB_EVENT_WORKERS = 4

# The number of seconds to buffer callback receiver bulk
# writes in memory before flushing via JobEvent.objects.bulk_create()
JOB_EVENT_BUFFER_SECONDS = 1

# The interval at which callback receiver statistics should be
# recorded
JOB_EVENT_STATISTICS_INTERVAL = 5

# The maximum size of the job event worker queue before requests are blocked
JOB_EVENT_MAX_QUEUE_SIZE = 10000

# The number of job events to migrate per-transaction when moving from int -> bigint
JOB_EVENT_MIGRATION_CHUNK_SIZE = 1000000

# The prefix of the redis key that stores metrics
SUBSYSTEM_METRICS_REDIS_KEY_PREFIX = "awx_metrics"

# Histogram buckets for the callback_receiver_batch_events_insert_db metric
SUBSYSTEM_METRICS_BATCH_INSERT_BUCKETS = [10, 50, 150, 350, 650, 2000]

# Interval in seconds for sending local metrics to other nodes
SUBSYSTEM_METRICS_INTERVAL_SEND_METRICS = 3

# Interval in seconds for saving local metrics to redis
SUBSYSTEM_METRICS_INTERVAL_SAVE_TO_REDIS = 2

# Record task manager metrics at the following interval in seconds
# If using Prometheus, it is recommended to be => the Prometheus scrape interval
SUBSYSTEM_METRICS_TASK_MANAGER_RECORD_INTERVAL = 15

# The maximum allowed jobs to start on a given task manager cycle
START_TASK_LIMIT = 100

# Time out task managers if they take longer than this many seconds, plus TASK_MANAGER_TIMEOUT_GRACE_PERIOD
# We have the grace period so the task manager can bail out before the timeout.
TASK_MANAGER_TIMEOUT = 300
TASK_MANAGER_TIMEOUT_GRACE_PERIOD = 60
TASK_MANAGER_LOCK_TIMEOUT = TASK_MANAGER_TIMEOUT + TASK_MANAGER_TIMEOUT_GRACE_PERIOD

# Number of seconds _in addition to_ the task manager timeout a job can stay
# in waiting without being reaped
JOB_WAITING_GRACE_PERIOD = 60

# Number of seconds after a container group job finished time to wait
# before the awx_k8s_reaper task will tear down the pods
K8S_POD_REAPER_GRACE_PERIOD = 60

# Any ANSIBLE_* settings will be passed to the task runner subprocess
# environment

# Do not want AWX to ask interactive questions and want it to be friendly with
# reprovisioning
ANSIBLE_HOST_KEY_CHECKING = False

# RHEL has too old of an SSH so ansible will select paramiko and this is VERY
# slow.
ANSIBLE_PARAMIKO_RECORD_HOST_KEYS = False

# Force ansible in color even if we don't have a TTY so we can properly colorize
# output
ANSIBLE_FORCE_COLOR = True

# If tmp generated inventory parsing fails (error state), fail playbook fast
ANSIBLE_INVENTORY_UNPARSED_FAILED = True

# Additional environment variables to be passed to the ansible subprocesses
AWX_TASK_ENV = {}

# Additional environment variables to apply when running ansible-galaxy commands
# to fetch Ansible content - roles and collections
GALAXY_TASK_ENV = {'ANSIBLE_FORCE_COLOR': 'false', 'GIT_SSH_COMMAND': "ssh -o StrictHostKeyChecking=no"}

# Rebuild Host Smart Inventory memberships.
AWX_REBUILD_SMART_MEMBERSHIP = False

# By default, allow arbitrary Jinja templating in extra_vars defined on a Job Template
ALLOW_JINJA_IN_EXTRA_VARS = 'template'

# Run project updates with extra verbosity
PROJECT_UPDATE_VVV = False

# Enable dynamically pulling roles from a requirement.yml file
# when updating SCM projects
# Note: This setting may be overridden by database settings.
AWX_ROLES_ENABLED = True

# Enable dynamically pulling collections from a requirement.yml file
# when updating SCM projects
# Note: This setting may be overridden by database settings.
AWX_COLLECTIONS_ENABLED = True

# Follow symlinks when scanning for playbooks
AWX_SHOW_PLAYBOOK_LINKS = False

# Applies to any galaxy server
GALAXY_IGNORE_CERTS = False

# Additional paths to show for jobs using process isolation.
# Note: This setting may be overridden by database settings.
AWX_ISOLATION_SHOW_PATHS = []

# The directory in which the service will create new temporary directories for job
# execution and isolation (such as credential files and custom
# inventory scripts).
# Note: This setting may be overridden by database settings.
AWX_ISOLATION_BASE_PATH = tempfile.gettempdir()

# User definable ansible callback plugins
# Note: This setting may be overridden by database settings.
AWX_ANSIBLE_CALLBACK_PLUGINS = ""

# Default list of modules allowed for ad hoc commands.
# Note: This setting may be overridden by database settings.
AD_HOC_COMMANDS = [
    'command',
    'shell',
    'yum',
    'apt',
    'apt_key',
    'apt_repository',
    'apt_rpm',
    'service',
    'group',
    'user',
    'mount',
    'ping',
    'selinux',
    'setup',
    'win_ping',
    'win_service',
    'win_updates',
    'win_group',
    'win_user',
]
