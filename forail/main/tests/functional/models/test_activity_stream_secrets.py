"""The Forail models connected to the activity stream.

Each of these was registered with activity_stream_registrar without a
matching relation on ActivityStream, so saving one while the activity stream
was enabled -- the default -- raised AttributeError: a 500 on every create
through the API. These tests save, update and delete each model with the
activity stream on, and check nothing that authenticates ends up in it.
"""

import json

import pytest

from django.test import override_settings

from forail.main.models import ActivityStream
from forail.main.models.drift import DriftAlertRule
from forail.main.models.eda import EventRule, OutboundWebhook
from forail.main.models.policy import Policy
from forail.main.models.scanner import Scanner
from forail.main.models.service_catalog import ServiceCatalogItem, ServiceRequest
from forail.main.models.webauthn import WebAuthnCredential
from forail.main.signals import model_serializer_mapping
from forail.main.utils import camelcase_to_underscore
from forail.main.utils.common import get_allowed_fields

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures('activity_stream_on')]


@pytest.fixture
def activity_stream_on():
    # No OPA sidecar here: an unset URL makes the policy sync a logged no-op.
    with override_settings(ACTIVITY_STREAM_ENABLED=True, OPA_SERVER_URL=''):
        yield


def _make(model, organization, admin_user):
    if model is EventRule:
        return EventRule.objects.create(name='r', organization=organization, webhook_path='r-path')
    if model is OutboundWebhook:
        return OutboundWebhook.objects.create(
            name='w', organization=organization, url='https://hooks.example/f', webhook_key='hmac-SECRET',
            custom_headers={'Authorization': 'Bearer HEADER-SECRET'}, events=['job.failed'],
        )
    if model is ServiceRequest:
        item = ServiceCatalogItem.objects.create(name='item', organization=organization)
        return ServiceRequest.objects.create(catalog_item=item, requested_by=admin_user, extra_vars={'db_password': 'SURVEY-SECRET'})
    if model is WebAuthnCredential:
        return WebAuthnCredential.objects.create(user=admin_user, credential_id=b'cred-SECRET', public_key=b'key-SECRET', label='yubikey')
    return model.objects.create(name='x', organization=organization)


MODELS = [EventRule, OutboundWebhook, DriftAlertRule, ServiceCatalogItem, ServiceRequest, WebAuthnCredential, Policy, Scanner]


def _entries(obj):
    return ActivityStream.objects.filter(object1=camelcase_to_underscore(type(obj).__name__))


@pytest.mark.parametrize('model', MODELS, ids=lambda m: m.__name__)
def test_create_update_delete_are_recorded(model, organization, admin_user):
    obj = _make(model, organization, admin_user)
    created = _entries(obj).get(operation='create')
    assert obj in getattr(created, camelcase_to_underscore(model.__name__)).all()

    if model is ServiceRequest:
        obj.justification = 'changed'
    elif model is WebAuthnCredential:
        obj.label = 'changed'
    else:
        obj.description = 'changed'
    obj.save()
    assert _entries(obj).filter(operation='update').exists()

    obj.delete()
    assert _entries(obj).filter(operation='delete').exists()


@pytest.mark.parametrize('model', [OutboundWebhook, ServiceRequest, WebAuthnCredential], ids=lambda m: m.__name__)
def test_secrets_stay_out_of_the_activity_stream(model, organization, admin_user):
    obj = _make(model, organization, admin_user)
    if model is OutboundWebhook:
        obj.webhook_key = 'rotated-SECRET'
        obj.custom_headers = {'Authorization': 'Bearer NEW-SECRET'}
    elif model is ServiceRequest:
        obj.extra_vars = {'db_password': 'NEW-SURVEY-SECRET'}
    else:
        obj.public_key = b'new-key-SECRET'
    obj.save()
    obj.delete()

    dumped = json.dumps([e.changes for e in _entries(obj)])
    assert 'SECRET' not in dumped, dumped


def test_service_request_approval_is_recorded(organization, admin_user):
    request = _make(ServiceRequest, organization, admin_user)
    request.status = 'approved'
    request.approved_by = admin_user
    request.save()
    update = _entries(request).get(operation='update')
    assert 'approved' in update.changes


@pytest.mark.parametrize('model', MODELS, ids=lambda m: m.__name__)
def test_timestamps_are_not_part_of_the_diff(model):
    assert 'modified' not in get_allowed_fields(model(), model_serializer_mapping())
