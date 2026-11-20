"""The client for the Forail Mobile service API, against a recorded fake session."""

import pytest
import requests
from django.test import override_settings

from forail.main.services import forail_mobile
from forail.main.services.forail_mobile import ForailMobileClient

# The client logs a warning on the error paths below, and the external-logger
# filter on that handler reads the DB-backed LOG_AGGREGATOR_ENABLED setting.
# That lookup is cached, so whether it touches the database depends on xdist
# cache warmth -- which made these tests flakily raise "Database access not
# allowed". Give the whole module DB access so the setting read is deterministic.
pytestmark = pytest.mark.django_db


class Response:
    def __init__(self, status_code, body=None, text=''):
        self.status_code = status_code
        self._body = body
        self.text = text
        self.content = b'' if body is None and not text else b'x'

    def json(self):
        if self._body is None:
            raise ValueError('no json')
        return self._body


class Session:
    def __init__(self, *responses, error=None):
        self.responses = list(responses)
        self.error = error
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        if self.error:
            raise self.error
        return self.responses.pop(0)


def client(session):
    return ForailMobileClient(base_url='http://mobile.test/', token='s3cret', timeout=3, session=session)


def test_create_sends_the_service_token_and_never_follows_redirects():
    session = Session(Response(201, {'id': 'b7f0', 'name': 'web-01'}))
    assert client(session).create_server('web-01', 4, 9) == 'b7f0'
    method, url, kwargs = session.requests[0]
    assert (method, url) == ('POST', 'http://mobile.test/api/v1/service/servers')
    assert kwargs['headers']['Authorization'] == 'Service s3cret'
    assert kwargs['json'] == {'name': 'web-01', 'organization': '4', 'owner': '9'}
    assert kwargs['allow_redirects'] is False
    assert kwargs['timeout'] == 3


def test_rotate_returns_an_enrollment_code():
    session = Session(Response(201, {'server_id': 'b7f0', 'code': 'fme_x', 'expires_at': '2026-11-01T10:10:00Z'}))
    code = client(session).rotate('b7f0', issued_by=3)
    assert code.code == 'fme_x'
    assert session.requests[0][1].endswith('/api/v1/service/servers/b7f0/rotate')
    assert session.requests[0][2]['json'] == {'issued_by': '3'}


@pytest.mark.parametrize(
    'status,error',
    [
        (409, forail_mobile.MobileConflict),
        (404, forail_mobile.MobileNotFound),
        (500, forail_mobile.MobileUnavailable),
        (401, forail_mobile.MobileUnavailable),
        (302, forail_mobile.MobileUnavailable),
    ],
)
def test_error_mapping(status, error):
    with pytest.raises(error):
        client(Session(Response(status, {'message': 'nope'}))).create_server('web-01', 1, 1)


def test_unreachable_is_unavailable():
    with pytest.raises(forail_mobile.MobileUnavailable):
        client(Session(error=requests.ConnectionError('refused'))).statuses()


def test_delete_of_a_server_already_gone_is_fine():
    client(Session(Response(404, {'message': 'gone'}))).delete_server('b7f0')


def test_not_configured_is_unavailable():
    with pytest.raises(forail_mobile.MobileUnavailable):
        ForailMobileClient(base_url='', token='', session=Session()).statuses()


def test_statuses_keyed_by_id():
    session = Session(Response(200, [{'id': 'a', 'online': True, 'last_report_at': 't'}, {'id': 'b', 'online': False}]))
    statuses = client(session).statuses()
    assert statuses['a'].online is True and statuses['b'].last_report_at is None


@override_settings(FORAIL_MOBILE_SERVICE_TOKEN='s3cret')
@pytest.mark.parametrize(
    'header,ok',
    [
        ('Service s3cret', True),
        ('Service  s3cret', True),
        ('Bearer s3cret', False),
        ('Service wrong', False),
        ('Service ', False),
        ('', False),
        (None, False),
    ],
)
def test_service_token_matches(header, ok):
    assert forail_mobile.service_token_matches(header) is ok


@override_settings(FORAIL_MOBILE_SERVICE_TOKEN='')
def test_empty_token_never_matches():
    assert forail_mobile.service_token_matches('Service ') is False


@override_settings(FORAIL_MOBILE_URL='http://mobile.svc:8080/', FORAIL_MOBILE_PUBLIC_URL='')
def test_public_url_falls_back_to_the_internal_one():
    assert forail_mobile.public_api_url() == 'http://mobile.svc:8080'
