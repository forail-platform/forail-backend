# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

"""
AWX custom middleware classes.

Middleware ordering dependencies:
- SettingsCacheMiddleware: early, before any settings access
- TimingMiddleware: early, to capture full request time
- MigrationRanCheckMiddleware: before content processing
- DisableLocalAuthMiddleware: after AuthenticationMiddleware (needs request.user)
- URLModificationMiddleware: late, after auth and routing
- SessionTimeoutMiddleware: last, modifies response headers
"""

import functools
import hashlib
import logging
import threading
import time
import urllib.parse
from pathlib import Path, PurePosixPath

from django.conf import settings
from django.contrib.auth import logout
from django.db.migrations.recorder import MigrationRecorder
from django.db import connection
from django.shortcuts import redirect
from django.utils.deprecation import MiddlewareMixin
from django.urls import reverse, resolve

from forail.main import migrations
from forail.main.utils.profiling import AWXProfiler
from forail.main.utils.common import memoize
from forail.urls import get_urlpatterns


logger = logging.getLogger('forail.main.middleware')
perf_logger = logging.getLogger('forail.analytics.performance')


# Thread-local storage for request context (IP, user agent, session)
# Used by ActivityStream signals to capture audit metadata.
_request_context = threading.local()


def get_request_context():
    """Return dict with actor_ip, actor_user_agent, actor_session_id from current request."""
    return {
        'actor_ip': getattr(_request_context, 'ip', ''),
        'actor_user_agent': getattr(_request_context, 'user_agent', ''),
        'actor_session_id': getattr(_request_context, 'session_id', ''),
    }


class RequestContextMiddleware(MiddlewareMixin):
    """
    Captures request metadata (IP, User-Agent, session ID) into thread-local
    storage so that ActivityStream signals can include it in audit entries.
    Must be placed after AuthenticationMiddleware.
    """

    def process_request(self, request):
        # IP address — only trust X-Forwarded-For when the direct peer is a
        # configured trusted proxy (PROXY_IP_ALLOWED_LIST). Otherwise a client
        # could forge X-Forwarded-For and spoof the recorded audit actor_ip.
        remote_addr = request.META.get('REMOTE_ADDR', '')
        forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
        proxy_allowed = getattr(settings, 'PROXY_IP_ALLOWED_LIST', None) or []
        if forwarded and remote_addr in proxy_allowed:
            _request_context.ip = forwarded.split(',')[0].strip()
        else:
            _request_context.ip = remote_addr

        # User agent
        _request_context.user_agent = request.META.get('HTTP_USER_AGENT', '')[:512]

        # Session ID — store a one-way hash, never the live session key. Anyone who
        # can read the audit trail must not be able to lift a usable key and hijack
        # the actor's session. SHA-256 hex is 64 chars, matching the field width.
        session_key = getattr(getattr(request, 'session', None), 'session_key', None)
        _request_context.session_id = hashlib.sha256(session_key.encode()).hexdigest() if session_key else ''

    def process_response(self, request, response):
        _request_context.ip = ''
        _request_context.user_agent = ''
        _request_context.session_id = ''
        return response


class SettingsCacheMiddleware(MiddlewareMixin):
    """
    Clears the in-memory settings cache at the beginning of a request.
    We do this so that a script can POST to /api/v2/settings/all/ and then
    right away GET /api/v2/settings/all/ and see the updated value.
    """

    def process_request(self, request):
        settings._awx_conf_memoizedcache.clear()


class TimingMiddleware(threading.local, MiddlewareMixin):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.prof = AWXProfiler("TimingMiddleware")

    def process_request(self, request):
        self.start_time = time.time()
        if settings.AWX_REQUEST_PROFILE:
            self.prof.start()

    def process_response(self, request, response):
        if not hasattr(self, 'start_time'):  # some tools may not invoke process_request
            return response
        total_time = time.time() - self.start_time
        response['X-API-Total-Time'] = '%0.3fs' % total_time
        if settings.AWX_REQUEST_PROFILE:
            response['X-API-Profile-File'] = self.prof.stop()
        perf_logger.debug(
            f'request: {request}, response_time: {response["X-API-Total-Time"]}',
            extra=dict(python_objects=dict(request=request, response=response, X_API_TOTAL_TIME=response["X-API-Total-Time"])),
        )
        return response


class SessionTimeoutMiddleware(MiddlewareMixin):
    """
    Resets the session timeout for both the UI and the actual session for the API
    to the value of SESSION_COOKIE_AGE on every request if there is a valid session.
    """

    def process_response(self, request, response):
        should_skip = 'HTTP_X_WS_SESSION_QUIET' in request.META
        # Something went wrong, such as upgrade-in-progress page
        if not hasattr(request, 'session'):
            return response
        # Only update the session if it hasn't been flushed by being forced to log out.
        if request.session and not request.session.is_empty() and not should_skip:
            expiry = int(settings.SESSION_COOKIE_AGE)
            request.session.set_expiry(expiry)
            response['Session-Timeout'] = expiry
        return response


class DisableLocalAuthMiddleware(MiddlewareMixin):
    """
    Respects the presence of the DISABLE_LOCAL_AUTH setting and forces
    local-only users to logout when they make a request.
    """

    def process_request(self, request):
        if settings.DISABLE_LOCAL_AUTH:
            user = request.user
            if not user.pk:
                return
            if not (user.profile.ldap_dn or user.social_auth.exists() or user.enterprise_auth.exists()):
                logout(request)


class WebAuthnMfaEnforcementMiddleware(MiddlewareMixin):
    """
    After primary auth completes, if any organization the user belongs to
    requires WebAuthn for them, mark the session as `mfa_pending`. The
    frontend interstitial drives the user through a WebAuthn assertion
    against /api/v2/webauthn/authenticate/{begin,complete}/, which clears
    the flag.

    Skips: anonymous users, the WebAuthn endpoints themselves, /api/login,
    /api/logout, and the static SSO callback paths.
    """

    SAFE_PATHS = (
        '/api/v2/webauthn/',
        '/api/login/',
        '/api/logout/',
        '/sso/',
        '/api/v2/me/',
        '/api/v2/ping/',
        '/api/v2/config/',
    )

    def process_request(self, request):
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            return

        path = request.path or ''
        for prefix in self.SAFE_PATHS:
            if path.startswith(prefix):
                return

        session = request.session
        if session.get('mfa_pending'):
            # Already flagged — let the frontend handle it
            return

        if session.get('mfa_satisfied_for') == user.id:
            return

        try:
            from forail.main.models.webauthn import is_webauthn_required
            from forail.main.models.organization import Organization
        except Exception:
            return

        is_admin = user.is_superuser or user.admin_of_organizations.exists() if hasattr(user, 'admin_of_organizations') else user.is_superuser

        # If any of the user's orgs require WebAuthn for this user, enforce.
        try:
            org_settings = Organization.objects.filter(
                member_role__members=user,
            ).values_list('webauthn_required', flat=True)
        except Exception:
            org_settings = []

        required = any(is_webauthn_required(s, is_admin) for s in org_settings)
        if not required:
            session['mfa_satisfied_for'] = user.id
            session.modified = True
            return

        # Mark pending and remember which user is being challenged
        session['mfa_pending'] = True
        session['mfa_pending_user'] = user.id
        session.modified = True


class URLModificationMiddleware(MiddlewareMixin):
    @staticmethod
    def _hijack_for_old_jt_name(node, kwargs, named_url):
        try:
            int(named_url)
            return False
        except ValueError:
            pass
        JobTemplate = node.model
        name = urllib.parse.unquote(named_url)
        return JobTemplate.objects.filter(name=name).order_by('organization__created').first()

    @classmethod
    def _named_url_to_pk(cls, node, resource, named_url):
        kwargs = {}
        if node.populate_named_url_query_kwargs(kwargs, named_url):
            match = node.model.objects.filter(**kwargs).first()
            if match:
                return str(match.pk)
            else:
                # if the name does *not* resolve to any actual resource,
                # we should still attempt to route it through so that 401s are
                # respected
                # using "zero" here will cause the URL regex to match e.g.,
                # /api/v2/users/<integer>/, but it also means that anonymous
                # users will go down the path of having their credentials
                # verified; in this way, *anonymous* users will that visit
                # /api/v2/users/invalid-username/ *won't* see a 404, they'll
                # see a 401 as if they'd gone to /api/v2/users/0/
                #
                return '0'
        if resource == 'job_templates' and '++' not in named_url:
            # special case for deprecated job template case
            # will not raise a 404 on its own
            jt = cls._hijack_for_old_jt_name(node, kwargs, named_url)
            if jt:
                return str(jt.pk)
        return named_url

    @classmethod
    def _convert_named_url(cls, url_path):
        default_prefix = PurePosixPath('/api/v2/')
        optional_prefix = PurePosixPath(f'/api/{settings.OPTIONAL_API_URLPATTERN_PREFIX}/v2/')

        url_path_original = url_path
        url_path = PurePosixPath(url_path)

        if set(optional_prefix.parts).issubset(set(url_path.parts)):
            url_prefix = optional_prefix
        elif set(default_prefix.parts).issubset(set(url_path.parts)):
            url_prefix = default_prefix
        else:
            return url_path_original

        # Remove prefix
        url_path = PurePosixPath(*url_path.parts[len(url_prefix.parts) :])
        try:
            resource_path = PurePosixPath(url_path.parts[0])
            name = url_path.parts[1]
            url_suffix = PurePosixPath(*url_path.parts[2:])  # remove name and resource
        except IndexError:
            return url_path_original

        resource = resource_path.parts[0]
        if resource in settings.NAMED_URL_MAPPINGS:
            pk = PurePosixPath(cls._named_url_to_pk(settings.NAMED_URL_GRAPH[settings.NAMED_URL_MAPPINGS[resource]], resource, name))
        else:
            return url_path_original

        parts = url_prefix.parts + resource_path.parts + pk.parts + url_suffix.parts
        return PurePosixPath(*parts).as_posix() + '/'

    def process_request(self, request):
        # Named URLs only exist under /api/, skip PurePosixPath processing for all other paths
        if not request.path_info.startswith('/api/'):
            return
        old_path = request.path_info
        new_path = self._convert_named_url(old_path)
        if request.path_info != new_path:
            request.environ['forail.named_url_rewritten'] = request.path
            request.path = request.path.replace(request.path_info, new_path)
            request.path_info = new_path


@memoize(ttl=20)
def is_migrating():
    migration_dir = Path(migrations.__path__[0])
    migration_files = list(migration_dir.glob('[0-9]*.py'))
    if not migration_files:
        return False
    latest = max(migration_files, key=lambda f: int(f.name.split('_', 1)[0]))
    latest_name = latest.name[: -len('.py')]
    return not MigrationRecorder(connection).migration_qs.filter(app='main', name=latest_name).exists()


class MigrationRanCheckMiddleware(MiddlewareMixin):
    def process_request(self, request):
        if is_migrating() and getattr(resolve(request.path), 'url_name', '') != 'migrations_notran':
            return redirect(reverse("ui:migrations_notran"))


class OptionalURLPrefixPath(MiddlewareMixin):
    @functools.lru_cache
    def _url_optional(self, prefix):
        # Relevant Django code path https://github.com/django/django/blob/stable/4.2.x/django/core/handlers/base.py#L300
        #
        # resolve_request(request)
        #   get_resolver(request.urlconf)
        #     _get_cached_resolver(request.urlconf) <-- cached via @functools.cache
        #
        # Django will attempt to cache the value(s) of request.urlconf
        # Being hashable is a prerequisite for being cachable.
        # tuple() is hashable list() is not.
        # Hence the tuple(list()) wrap.
        return tuple(get_urlpatterns(prefix=prefix))

    def process_request(self, request):
        prefix = settings.OPTIONAL_API_URLPATTERN_PREFIX

        if request.path.startswith(f"/api/{prefix}"):
            request.urlconf = self._url_optional(prefix)
        else:
            request.urlconf = 'forail.urls'
