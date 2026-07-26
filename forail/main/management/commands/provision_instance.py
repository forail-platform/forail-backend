# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved

import os

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.conf import settings

from forail.main.models import Instance


class Command(BaseCommand):
    """
    Internal tower command.
    Register this instance with the database for HA tracking.
    """

    help = (
        "Add instance to the database. "
        "When no options are provided, values from Django settings will be used to register the current system, "
        "as well as the default queues if needed (only used or enabled for Kubernetes installs). "
        "Override with `--hostname`."
    )

    NODE_TYPES = ['control', 'execution', 'hop', 'hybrid']

    def add_arguments(self, parser):
        parser.add_argument('--hostname', dest='hostname', type=str, help="Hostname used during provisioning")
        parser.add_argument('--node_type', type=str, default='hybrid', choices=self.NODE_TYPES, help="Instance Node type")
        parser.add_argument('--uuid', type=str, help="Instance UUID")

    def _make_regular_instance_group(self, name):
        """Demote a queue that a previous run (or post_migrate) left as a ContainerGroup.

        RegisterQueue only ever sets is_container_group when asked to turn it
        *on*, so this cannot be expressed by passing False to it.
        """
        from forail.main.models import InstanceGroup

        ig = InstanceGroup.objects.filter(name=name, is_container_group=True).first()
        if ig:
            ig.is_container_group = False
            ig.pod_spec_override = ''
            ig.save(update_fields=['is_container_group', 'pod_spec_override'])
            print("Instance group {} is now a regular instance group".format(name))

    def _register_hostname(self, hostname, node_type, uuid):
        if not hostname:
            if not settings.AWX_AUTO_DEPROVISION_INSTANCES:
                raise CommandError('Registering with values from settings only intended for use in K8s installs')

            from forail.main.management.commands.register_queue import RegisterQueue

            # The task pod re-runs this on every start, and both calls below
            # overwrite what is already in the database. Hardcoding the node
            # type and the container-group flag therefore un-did whatever the
            # installer had set, every restart and every rolling upgrade. Take
            # the intent from the environment the deployment already provides,
            # and keep the previous values as the defaults for a multi-node
            # install that has no opinion.
            pod_node_type = os.environ.get('FORAIL_NODE_TYPE') or 'control'
            if pod_node_type not in self.NODE_TYPES:
                raise CommandError('FORAIL_NODE_TYPE must be one of {}, got {!r}'.format(', '.join(self.NODE_TYPES), pod_node_type))

            (changed, instance) = Instance.objects.register(ip_address=os.environ.get('MY_POD_IP'), node_type=pod_node_type, node_uuid=settings.SYSTEM_UUID)
            RegisterQueue(settings.DEFAULT_CONTROL_PLANE_QUEUE_NAME, 100, 0, [], is_container_group=False).register()

            if pod_node_type in ('hybrid', 'execution'):
                # This pod runs jobs itself, through the local receptor work
                # command, so the default queue has to be a regular instance
                # group that contains it. Both halves matter: a regular group
                # with no execution-capable member accepts launches and never
                # runs them -- the job sits in "pending" with nothing but
                # "not enough available capacity" to go on.
                RegisterQueue(settings.DEFAULT_EXECUTION_QUEUE_NAME, 100, 0, [instance.hostname]).register()
                self._make_regular_instance_group(settings.DEFAULT_EXECUTION_QUEUE_NAME)
            else:
                RegisterQueue(
                    settings.DEFAULT_EXECUTION_QUEUE_NAME,
                    100,
                    0,
                    [],
                    is_container_group=True,
                    pod_spec_override=settings.DEFAULT_EXECUTION_QUEUE_POD_SPEC_OVERRIDE,
                    max_forks=settings.DEFAULT_EXECUTION_QUEUE_MAX_FORKS,
                    max_concurrent_jobs=settings.DEFAULT_EXECUTION_QUEUE_MAX_CONCURRENT_JOBS,
                ).register()
        else:
            (changed, instance) = Instance.objects.register(hostname=hostname, node_type=node_type, node_uuid=uuid)
        if changed:
            print("Successfully registered instance {}".format(hostname))
        else:
            print("Instance already registered {}".format(instance.hostname))

        self.changed = changed

    @transaction.atomic
    def handle(self, **options):
        self.changed = False
        self._register_hostname(options.get('hostname'), options.get('node_type'), options.get('uuid'))
        if self.changed:
            print("(changed: True)")
