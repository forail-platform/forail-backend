"""Client for the Forail Mobile backend's service API (forail-mobile#44).

The platform decides who may reach a monitored server; the mobile backend keeps
the server's agent token and telemetry. Every call here is service-to-service,
authenticated with ``FORAIL_MOBILE_SERVICE_TOKEN`` -- never a user's token.

The client never returns a long-lived agent token. Rotation revokes the old
token and hands back a one-time enrollment code, so the only secret a person
ever sees is good for ten minutes and one use.
"""

import hmac
import logging
from dataclasses import dataclass

import requests
from django.conf import settings

logger = logging.getLogger('forail.main.services.forail_mobile')

SERVICE_SCHEME = 'Service'


class MobileUnavailable(Exception):
    """The mobile backend is not configured, unreachable, or answered badly."""


class MobileConflict(Exception):
    """The mobile backend already has a server with that name in the organization."""


class MobileNotFound(Exception):
    """The mobile backend has no such server (deleted there, or never created)."""


@dataclass(frozen=True)
class EnrollmentCode:
    code: str
    expires_at: str


@dataclass(frozen=True)
class ServerStatus:
    online: bool
    last_report_at: str | None


def enabled():
    return bool(settings.FORAIL_MOBILE_URL and settings.FORAIL_MOBILE_SERVICE_TOKEN)


def service_token_matches(header_value):
    """True if an ``Authorization`` header carries the configured service token."""
    token = settings.FORAIL_MOBILE_SERVICE_TOKEN
    if not token or not header_value:
        return False
    scheme, _, presented = header_value.partition(' ')
    if scheme != SERVICE_SCHEME or not presented:
        return False
    return hmac.compare_digest(presented.strip().encode(), token.encode())


def public_api_url():
    """The address an agent on the monitored server uses, for the install command."""
    return (settings.FORAIL_MOBILE_PUBLIC_URL or settings.FORAIL_MOBILE_URL).rstrip('/')


class ForailMobileClient:
    def __init__(self, base_url=None, token=None, timeout=None, session=None):
        self.base_url = (base_url if base_url is not None else settings.FORAIL_MOBILE_URL).rstrip('/')
        self.token = token if token is not None else settings.FORAIL_MOBILE_SERVICE_TOKEN
        self.timeout = timeout if timeout is not None else settings.FORAIL_MOBILE_TIMEOUT
        self.session = session or requests

    # --- calls ------------------------------------------------------------------

    def create_server(self, name, organization_id, owner_id):
        body = self._call('POST', '/api/v1/service/servers', {'name': name, 'organization': str(organization_id), 'owner': str(owner_id)}, expect=(201,))
        return body['id']

    def enrollment_code(self, server_id, issued_by=None):
        body = self._call('POST', f'/api/v1/service/servers/{server_id}/enrollment-code', {'issued_by': _str_or_none(issued_by)}, expect=(201,))
        return EnrollmentCode(code=body['code'], expires_at=body['expires_at'])

    def rotate(self, server_id, issued_by=None):
        """Revoke the agent's token; the host re-enrolls with the code returned."""
        body = self._call('POST', f'/api/v1/service/servers/{server_id}/rotate', {'issued_by': _str_or_none(issued_by)}, expect=(201,))
        return EnrollmentCode(code=body['code'], expires_at=body['expires_at'])

    def delete_server(self, server_id):
        try:
            self._call('DELETE', f'/api/v1/service/servers/{server_id}', None, expect=(204,))
        except MobileNotFound:
            pass  # already gone there; deleting here is what matters

    def statuses(self):
        """Online state of every server the mobile backend knows, keyed by id."""
        body = self._call('GET', '/api/v1/service/servers', None, expect=(200,))
        return {row['id']: ServerStatus(online=bool(row.get('online')), last_report_at=row.get('last_report_at')) for row in body}

    def link(self, server_id, organization_id, owner_id):
        """Tell the mobile backend which organization and owner a legacy server now has."""
        self._call('PATCH', f'/api/v1/service/servers/{server_id}', {'organization': str(organization_id), 'owner': _str_or_none(owner_id)}, expect=(200, 204))

    def servers(self):
        """Every server, with the legacy member list, for import_monitored_servers."""
        return self._call('GET', '/api/v1/service/servers', None, expect=(200,))

    # --- plumbing ---------------------------------------------------------------

    def _call(self, method, path, payload, expect):
        if not (self.base_url and self.token):
            raise MobileUnavailable('Forail Mobile is not configured (FORAIL_MOBILE_URL, FORAIL_MOBILE_SERVICE_TOKEN).')
        try:
            response = self.session.request(
                method,
                self.base_url + path,
                json=payload,
                headers={'Authorization': f'{SERVICE_SCHEME} {self.token}', 'Accept': 'application/json'},
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as e:
            logger.warning('Forail Mobile %s %s failed: %s', method, path, e)
            raise MobileUnavailable('Forail Mobile is unreachable.') from e

        if response.status_code in expect:
            if response.status_code == 204 or not response.content:
                return None
            try:
                return response.json()
            except ValueError as e:
                raise MobileUnavailable('Forail Mobile answered with something that is not JSON.') from e
        if response.status_code == 409:
            raise MobileConflict(_error_message(response))
        if response.status_code == 404:
            raise MobileNotFound(_error_message(response))
        logger.warning('Forail Mobile %s %s answered %s', method, path, response.status_code)
        raise MobileUnavailable(f'Forail Mobile answered {response.status_code}.')


def _str_or_none(value):
    return None if value is None else str(value)


def _error_message(response):
    try:
        return response.json().get('message') or response.text[:200]
    except ValueError:
        return response.text[:200]
