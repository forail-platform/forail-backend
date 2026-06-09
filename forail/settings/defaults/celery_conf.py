# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

# Celery broker, beat schedule, caches, and cluster settings

from datetime import timedelta


# heartbeat period can factor into some forms of logic, so it is maintained as a setting here
CLUSTER_NODE_HEARTBEAT_PERIOD = 60

# Number of missed heartbeats until a node gets marked as lost
CLUSTER_NODE_MISSED_HEARTBEAT_TOLERANCE = 2

RECEPTOR_SERVICE_ADVERTISEMENT_PERIOD = 60  # https://github.com/ansible/receptor/blob/aa1d589e154d8a0cb99a220aff8f98faf2273be6/pkg/netceptor/netceptor.go#L34
EXECUTION_NODE_REMEDIATION_CHECKS = 60 * 30  # once every 30 minutes check if an execution node errors have been resolved

# Amount of time dispatcher will try to reconnect to database for jobs and consuming new work
DISPATCHER_DB_DOWNTIME_TOLERANCE = 40

BROKER_URL = 'unix:///var/run/redis/redis.sock'
CELERYBEAT_SCHEDULE = {
    'tower_scheduler': {'task': 'forail.main.tasks.system.awx_periodic_scheduler', 'schedule': timedelta(seconds=30), 'options': {'expires': 20}},
    'cluster_heartbeat': {
        'task': 'forail.main.tasks.system.cluster_node_heartbeat',
        'schedule': timedelta(seconds=CLUSTER_NODE_HEARTBEAT_PERIOD),
        'options': {'expires': 50},
    },
    'gather_analytics': {'task': 'forail.main.tasks.system.gather_analytics', 'schedule': timedelta(minutes=5)},
    'task_manager': {'task': 'forail.main.scheduler.tasks.task_manager', 'schedule': timedelta(seconds=20), 'options': {'expires': 20}},
    'dependency_manager': {'task': 'forail.main.scheduler.tasks.dependency_manager', 'schedule': timedelta(seconds=20), 'options': {'expires': 20}},
    'k8s_reaper': {'task': 'forail.main.tasks.system.awx_k8s_reaper', 'schedule': timedelta(seconds=60), 'options': {'expires': 50}},
    'receptor_reaper': {'task': 'forail.main.tasks.system.awx_receptor_workunit_reaper', 'schedule': timedelta(seconds=60)},
    'send_subsystem_metrics': {'task': 'forail.main.analytics.analytics_tasks.send_subsystem_metrics', 'schedule': timedelta(seconds=20)},
    'cleanup_images': {'task': 'forail.main.tasks.system.cleanup_images_and_files', 'schedule': timedelta(hours=3)},
    'cleanup_host_metrics': {'task': 'forail.main.tasks.host_metrics.cleanup_host_metrics', 'schedule': timedelta(hours=3, minutes=30)},
    'host_metric_summary_monthly': {'task': 'forail.main.tasks.host_metrics.host_metric_summary_monthly', 'schedule': timedelta(hours=4)},
    'periodic_resource_sync': {'task': 'forail.main.tasks.system.periodic_resource_sync', 'schedule': timedelta(minutes=15)},
    'observability_active_jobs': {
        'task': 'forail.main.tasks.observability.update_active_jobs_gauge_task',
        'schedule': timedelta(seconds=30),
        'options': {'expires': 25},
    },
    'tenancy_recalculate': {
        'task': 'forail.main.tasks.tenancy.recalculate_tenant_usage_all',
        'schedule': timedelta(seconds=300),
        'options': {'expires': 280},
    },
    'tenancy_ensure_queues': {
        'task': 'forail.main.tasks.tenancy.ensure_all_tenant_queues',
        'schedule': timedelta(seconds=600),
        'options': {'expires': 580},
    },
}

# Django Caching Configuration
DJANGO_REDIS_IGNORE_EXCEPTIONS = True
CACHES = {'default': {'BACKEND': 'forail.main.cache.AWXRedisCache', 'LOCATION': 'unix:///var/run/redis/redis.sock?db=1'}}

CALLBACK_QUEUE = "callback_tasks"
