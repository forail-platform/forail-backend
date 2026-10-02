"""Policy <-> OPA sidecar sync must never break saving or deleting a Policy."""

import pytest

from django.test import override_settings

from forail.main.models.policy import Policy

REGO = 'package forail.launch\n\ndeny[msg] { false; msg := "never" }\n'

# Nothing listens on port 9 (discard); a refused connection is immediate.
UNREACHABLE = 'http://127.0.0.1:9'


@pytest.mark.django_db
@override_settings(OPA_SERVER_URL=UNREACHABLE)
def test_saving_a_policy_with_opa_down_records_the_failure(organization):
    policy = Policy.objects.create(name='p', organization=organization, rego_module=REGO)
    policy.refresh_from_db()
    assert policy.last_sync_status == 'failed'


@pytest.mark.django_db
@override_settings(OPA_SERVER_URL=UNREACHABLE)
def test_deleting_a_policy_with_opa_down_still_deletes(organization):
    policy = Policy.objects.create(name='p', organization=organization, rego_module=REGO)
    policy.delete()
    assert not Policy.objects.filter(name='p').exists()


@pytest.mark.django_db
def test_successful_push_marks_the_policy_synced(organization, mocker):
    put = mocker.patch('forail.main.policy.opa_client._put_text')
    with override_settings(OPA_SERVER_URL='http://opa:8181'):
        policy = Policy.objects.create(name='p', organization=organization, rego_module=REGO)
    policy.refresh_from_db()
    assert policy.last_sync_status == 'ok'
    url = put.call_args[0][0]
    assert url == 'http://opa:8181/v1/policies/forail_%d' % policy.id
