import pytest

from forail.main.management.commands.provision_instance import Command
from forail.main.models.ha import InstanceGroup, Instance
from forail.main.tasks.system import apply_cluster_membership_policies

from django.core.management.base import CommandError
from django.test.utils import override_settings


@pytest.mark.django_db
def test_traditional_registration():
    assert not Instance.objects.exists()
    assert not InstanceGroup.objects.exists()

    Command().handle(hostname='bar_node', node_type='execution', uuid='4321')

    inst = Instance.objects.first()
    assert inst.hostname == 'bar_node'
    assert inst.node_type == 'execution'
    assert inst.uuid == '4321'

    assert not InstanceGroup.objects.exists()


@pytest.mark.django_db
def test_register_self_openshift(monkeypatch):
    # Deployments set this; the default with it unset is what is under test.
    monkeypatch.delenv('FORAIL_NODE_TYPE', raising=False)
    assert not Instance.objects.exists()
    assert not InstanceGroup.objects.exists()

    with override_settings(AWX_AUTO_DEPROVISION_INSTANCES=True, CLUSTER_HOST_ID='foo_node', SYSTEM_UUID='12345'):
        Command().handle()
    inst = Instance.objects.first()
    assert inst.hostname == 'foo_node'
    assert inst.uuid == '12345'
    assert inst.node_type == 'control'

    apply_cluster_membership_policies()  # populate instance list using policy rules

    assert list(InstanceGroup.objects.get(name='default').instances.all()) == []  # container group
    assert list(InstanceGroup.objects.get(name='controlplane').instances.all()) == [inst]


@pytest.mark.django_db
def test_register_self_honours_node_type_from_environment(monkeypatch):
    monkeypatch.setenv('FORAIL_NODE_TYPE', 'hybrid')

    with override_settings(AWX_AUTO_DEPROVISION_INSTANCES=True, CLUSTER_HOST_ID='foo_node', SYSTEM_UUID='12345'):
        Command().handle()

    inst = Instance.objects.get(hostname='foo_node')
    assert inst.node_type == 'hybrid'

    # An execution-capable pod runs jobs itself, so the default queue has to be
    # a regular group that contains it. A regular group with no member accepts
    # launches and never runs them.
    default = InstanceGroup.objects.get(name='default')
    assert not default.is_container_group
    assert list(default.instances.all()) == [inst]


@pytest.mark.django_db
def test_register_self_demotes_a_container_group_left_by_an_earlier_run(monkeypatch):
    """An install that registered as control-only before must converge, not stay half-migrated."""
    with override_settings(AWX_AUTO_DEPROVISION_INSTANCES=True, CLUSTER_HOST_ID='foo_node', SYSTEM_UUID='12345'):
        monkeypatch.delenv('FORAIL_NODE_TYPE', raising=False)
        Command().handle()
        assert InstanceGroup.objects.get(name='default').is_container_group

        monkeypatch.setenv('FORAIL_NODE_TYPE', 'hybrid')
        Command().handle()

    default = InstanceGroup.objects.get(name='default')
    assert not default.is_container_group
    assert default.pod_spec_override == ''
    assert [i.hostname for i in default.instances.all()] == ['foo_node']


@pytest.mark.django_db
def test_register_self_does_not_demote_an_execution_capable_instance(monkeypatch):
    """The task pod re-runs this on every start; it must not undo its own node type.

    Registering with a hardcoded 'control' here is what left single-node
    deployments unable to execute anything after a pod restart or a rolling
    upgrade -- silently, since a control node accepts jobs and never runs them.
    """
    monkeypatch.setenv('FORAIL_NODE_TYPE', 'hybrid')

    with override_settings(AWX_AUTO_DEPROVISION_INSTANCES=True, CLUSTER_HOST_ID='foo_node', SYSTEM_UUID='12345'):
        Command().handle()
        Command().handle()

    assert Instance.objects.get(hostname='foo_node').node_type == 'hybrid'


@pytest.mark.django_db
def test_register_self_rejects_an_unknown_node_type(monkeypatch):
    monkeypatch.setenv('FORAIL_NODE_TYPE', 'worker')

    with override_settings(AWX_AUTO_DEPROVISION_INSTANCES=True, CLUSTER_HOST_ID='foo_node', SYSTEM_UUID='12345'):
        with pytest.raises(CommandError):
            Command().handle()

    assert not Instance.objects.exists()
