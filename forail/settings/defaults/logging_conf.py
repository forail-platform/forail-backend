# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

# Logging configuration

import os

from .base import LOG_ROOT

# Settings related to external logger configuration
LOG_AGGREGATOR_ENABLED = False
LOG_AGGREGATOR_TCP_TIMEOUT = 5
LOG_AGGREGATOR_VERIFY_CERT = True
LOG_AGGREGATOR_LEVEL = 'INFO'
LOG_AGGREGATOR_ACTION_QUEUE_SIZE = 131072
LOG_AGGREGATOR_ACTION_MAX_DISK_USAGE_GB = 1  # Action queue
LOG_AGGREGATOR_MAX_DISK_USAGE_PATH = '/var/lib/awx'
LOG_AGGREGATOR_RSYSLOGD_DEBUG = False
LOG_AGGREGATOR_RSYSLOGD_ERROR_LOG_FILE = '/var/log/tower/rsyslog.err'
API_400_ERROR_LOG_FORMAT = 'status {status_code} received by user {user_name} attempting to access {url_path} from {remote_addr}'

# Logging configuration.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'filters': {
        'require_debug_false': {'()': 'django.utils.log.RequireDebugFalse'},
        'require_debug_true': {'()': 'django.utils.log.RequireDebugTrue'},
        'require_debug_true_or_test': {'()': 'forail.main.utils.RequireDebugTrueOrTest'},
        'external_log_enabled': {'()': 'forail.main.utils.filters.ExternalLoggerEnabled'},
        'dynamic_level_filter': {'()': 'forail.main.utils.filters.DynamicLevelFilter'},
        'guid': {'()': 'forail.main.utils.filters.DefaultCorrelationId'},
    },
    'formatters': {
        'simple': {'format': '%(asctime)s %(levelname)-8s [%(guid)s] %(name)s %(message)s'},
        'json': {'()': 'forail.main.utils.formatters.LogstashFormatter'},
        'timed_import': {'()': 'forail.main.utils.formatters.TimeFormatter', 'format': '%(relativeSeconds)9.3f %(levelname)-8s %(message)s'},
        'dispatcher': {'format': '%(asctime)s %(levelname)-8s [%(guid)s] %(name)s PID:%(process)d %(message)s'},
    },
    # Extended below based on install scenario. You probably don't want to add something directly here.
    # See 'handler_config' below.
    'handlers': {
        'console': {
            '()': 'logging.StreamHandler',
            'level': 'DEBUG',
            'filters': ['dynamic_level_filter', 'guid'],
            'formatter': 'simple',
        },
        'null': {'class': 'logging.NullHandler'},
        'file': {'class': 'logging.NullHandler', 'formatter': 'simple'},
        'syslog': {'level': 'WARNING', 'filters': ['require_debug_false'], 'class': 'logging.NullHandler', 'formatter': 'simple'},
        'inventory_import': {'level': 'DEBUG', 'class': 'logging.StreamHandler', 'formatter': 'timed_import'},
        'external_logger': {
            'class': 'forail.main.utils.handlers.RSysLogHandler',
            'formatter': 'json',
            'address': '/var/run/awx-rsyslog/rsyslog.sock',
            'filters': ['external_log_enabled', 'dynamic_level_filter', 'guid'],
        },
        'otel': {'class': 'logging.NullHandler'},
    },
    'loggers': {
        'django': {'handlers': ['console']},
        'django.request': {'handlers': ['console', 'file', 'tower_warnings'], 'level': 'WARNING'},
        'ansible_base': {'handlers': ['console', 'file', 'tower_warnings']},
        'daphne': {'handlers': ['console', 'file', 'tower_warnings'], 'level': 'INFO'},
        'rest_framework.request': {'handlers': ['console', 'file', 'tower_warnings'], 'level': 'WARNING', 'propagate': False},
        'py.warnings': {'handlers': ['console']},
        'forail': {'handlers': ['console', 'file', 'tower_warnings', 'external_logger'], 'level': 'DEBUG'},
        'forail.conf': {'handlers': ['null'], 'level': 'WARNING'},
        'forail.conf.settings': {'handlers': ['null'], 'level': 'WARNING'},
        'forail.main': {'handlers': ['null']},
        'forail.main.commands.run_callback_receiver': {'handlers': ['callback_receiver'], 'level': 'INFO'},  # very noisey debug-level logs
        'forail.main.dispatch': {'handlers': ['dispatcher']},
        'forail.main.consumers': {'handlers': ['console', 'file', 'tower_warnings'], 'level': 'INFO'},
        'forail.main.rsyslog_configurer': {'handlers': ['rsyslog_configurer']},
        'forail.main.cache_clear': {'handlers': ['cache_clear']},
        'forail.main.ws_heartbeat': {'handlers': ['ws_heartbeat']},
        'forail.main.wsrelay': {'handlers': ['wsrelay']},
        'forail.main.commands.inventory_import': {'handlers': ['inventory_import'], 'propagate': False},
        'forail.main.tasks': {'handlers': ['task_system', 'external_logger', 'console'], 'propagate': False},
        'forail.main.analytics': {'handlers': ['task_system', 'external_logger', 'console'], 'level': 'INFO', 'propagate': False},
        'forail.main.scheduler': {'handlers': ['task_system', 'external_logger', 'console'], 'propagate': False},
        'forail.main.access': {'level': 'INFO'},  # very verbose debug-level logs
        'forail.main.signals': {'level': 'INFO'},  # very verbose debug-level logs
        'forail.api.permissions': {'level': 'INFO'},  # very verbose debug-level logs
        'forail.analytics': {'handlers': ['external_logger'], 'level': 'INFO', 'propagate': False},
        'forail.analytics.broadcast_websocket': {'handlers': ['console', 'file', 'wsrelay', 'external_logger'], 'level': 'INFO', 'propagate': False},
        'forail.analytics.performance': {'handlers': ['console', 'file', 'tower_warnings', 'external_logger'], 'level': 'DEBUG', 'propagate': False},
        'forail.analytics.job_lifecycle': {'handlers': ['console', 'job_lifecycle'], 'level': 'DEBUG', 'propagate': False},
        'django_auth_ldap': {'handlers': ['console', 'file', 'tower_warnings'], 'level': 'DEBUG'},
        'social': {'handlers': ['console', 'file', 'tower_warnings'], 'level': 'DEBUG'},
        'system_tracking_migrations': {'handlers': ['console', 'file', 'tower_warnings'], 'level': 'DEBUG'},
        'rbac_migrations': {'handlers': ['console', 'file', 'tower_warnings'], 'level': 'DEBUG'},
    },
}

# Log handler configuration. Keys are the name of the handler. Be mindful when renaming things here.
# People might have created custom settings files that augments the behavior of these.
# Specify 'filename' (used if the environment variable AWX_LOGGING_MODE is unset or 'file')
# and an optional 'formatter'. If no formatter is specified, 'simple' is used.
handler_config = {
    'tower_warnings': {'filename': 'tower.log'},
    'callback_receiver': {'filename': 'callback_receiver.log'},
    'dispatcher': {'filename': 'dispatcher.log', 'formatter': 'dispatcher'},
    'wsrelay': {'filename': 'wsrelay.log'},
    'task_system': {'filename': 'task_system.log'},
    'rbac_migrations': {'filename': 'tower_rbac_migrations.log'},
    'job_lifecycle': {'filename': 'job_lifecycle.log'},
    'rsyslog_configurer': {'filename': 'rsyslog_configurer.log'},
    'cache_clear': {'filename': 'cache_clear.log'},
    'ws_heartbeat': {'filename': 'ws_heartbeat.log'},
}

# If running on a VM, we log to files. When running in a container, we log to stdout.
logging_mode = os.getenv('AWX_LOGGING_MODE', 'file')
if logging_mode not in ('file', 'stdout'):
    raise Exception("AWX_LOGGING_MODE must be 'file' or 'stdout'")

for name, config in handler_config.items():
    # Common log handler config. Don't define a level here, it's set by settings.LOG_AGGREGATOR_LEVEL
    LOGGING['handlers'][name] = {'filters': ['dynamic_level_filter', 'guid'], 'formatter': config.get('formatter', 'simple')}

    if logging_mode == 'file':
        LOGGING['handlers'][name]['class'] = 'logging.handlers.WatchedFileHandler'
        LOGGING['handlers'][name]['filename'] = os.path.join(LOG_ROOT, config['filename'])

    if logging_mode == 'stdout':
        LOGGING['handlers'][name]['class'] = 'logging.NullHandler'

# Prevents logging to stdout on traditional VM installs
if logging_mode == 'file':
    LOGGING['handlers']['console']['filters'].insert(0, 'require_debug_true_or_test')

# Apply coloring to messages logged to the console
COLOR_LOGS = False
