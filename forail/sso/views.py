# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

# Python
import urllib.parse
import logging

# Django
from django.urls import reverse
from django.http import HttpResponse
from django.views.generic import View
from django.views.generic.base import RedirectView
from django.utils.encoding import smart_str
from django.conf import settings

logger = logging.getLogger('forail.sso.views')


class BaseRedirectView(RedirectView):
    # Not permanent: a browser caches a 301, and where SSO lands is a
    # deployment decision that can change.
    permanent = False

    def get_redirect_url(self, *args, **kwargs):
        # The frontend is forail-frontend, served at the site root with a
        # browser-history router. Upstream AWX sent users to the legacy UI
        # with the path as a fragment; that page is never built here, so a
        # successful SSO login used to end on a blank screen.
        last_path = urllib.parse.unquote(self.request.COOKIES.get('lastPath', '')).strip('"')
        # Only same-site absolute paths: '//evil.example' and anything with a
        # scheme would turn the cookie into an open redirect.
        if last_path.startswith('/') and not last_path.startswith('//') and '\\' not in last_path:
            return urllib.parse.quote(last_path, safe="/?=&-_.~%")
        return '/'


sso_error = BaseRedirectView.as_view()
sso_inactive = BaseRedirectView.as_view()


class CompleteView(BaseRedirectView):
    def dispatch(self, request, *args, **kwargs):
        response = super(CompleteView, self).dispatch(request, *args, **kwargs)
        if self.request.user and self.request.user.is_authenticated:
            logger.info(smart_str(u"User {} logged in".format(self.request.user.username)))
            response.set_cookie(
                'userLoggedIn', 'true', secure=getattr(settings, 'SESSION_COOKIE_SECURE', False), samesite=getattr(settings, 'USER_COOKIE_SAMESITE', 'Lax')
            )
            response.setdefault('X-API-Session-Cookie-Name', getattr(settings, 'SESSION_COOKIE_NAME', 'awx_sessionid'))
        return response


sso_complete = CompleteView.as_view()


class MetadataView(View):
    def get(self, request, *args, **kwargs):
        from social_django.utils import load_backend, load_strategy

        complete_url = reverse('social:complete', args=('saml',))
        try:
            saml_backend = load_backend(load_strategy(request), 'saml', redirect_uri=complete_url)
            metadata, errors = saml_backend.generate_metadata_xml()
        except Exception as e:
            logger.exception('unable to generate SAML metadata')
            errors = e
        if not errors:
            return HttpResponse(content=metadata, content_type='text/xml')
        else:
            return HttpResponse(content=str(errors), content_type='text/plain')


saml_metadata = MetadataView.as_view()
