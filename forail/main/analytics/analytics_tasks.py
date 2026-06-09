# Python
import logging

# AWX
from forail.main.analytics.subsystem_metrics import DispatcherMetrics, CallbackReceiverMetrics
from forail.main.dispatch.publish import task
from forail.main.dispatch import get_task_queuename

logger = logging.getLogger('forail.main.scheduler')


@task(queue=get_task_queuename)
def send_subsystem_metrics():
    DispatcherMetrics().send_metrics()
    CallbackReceiverMetrics().send_metrics()
