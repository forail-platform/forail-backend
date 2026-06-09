# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

from collections import OrderedDict

from django.conf import settings

from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from social_core.backends.utils import load_backends

from forail.api.generics import APIView


class AuthView(APIView):
    '''List enabled single-sign-on endpoints'''

    authentication_classes = []
    permission_classes = (AllowAny,)
    swagger_topic = 'System Configuration'

    def get(self, request):
        from rest_framework.reverse import reverse

        data = OrderedDict()
        err_backend, err_message = request.session.get('social_auth_error', (None, None))
        auth_backends = list(load_backends(settings.AUTHENTICATION_BACKENDS, force_load=True).items())
        # Return auth backends in consistent order: Google, GitHub, SAML.
        auth_backends.sort(key=lambda x: 'g' if x[0] == 'google-oauth2' else x[0])
        for name, backend in auth_backends:
            login_url = reverse('social:begin', args=(name,))
            complete_url = request.build_absolute_uri(reverse('social:complete', args=(name,)))
            backend_data = {'login_url': login_url, 'complete_url': complete_url}
            if name == 'saml':
                backend_data['metadata_url'] = reverse('sso:saml_metadata')
                for idp in sorted(settings.SOCIAL_AUTH_SAML_ENABLED_IDPS.keys()):
                    saml_backend_data = dict(backend_data.items())
                    saml_backend_data['login_url'] = '%s?idp=%s' % (login_url, idp)
                    full_backend_name = '%s:%s' % (name, idp)
                    if (err_backend == full_backend_name or err_backend == name) and err_message:
                        saml_backend_data['error'] = err_message
                    data[full_backend_name] = saml_backend_data
            else:
                if err_backend == name and err_message:
                    backend_data['error'] = err_message
                data[name] = backend_data
        return Response(data)
