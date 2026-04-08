from django.urls import re_path

from forge.api.views.webauthn import (
    WebAuthnCredentialList,
    WebAuthnCredentialDetail,
    WebAuthnRegisterBegin,
    WebAuthnRegisterComplete,
    WebAuthnAuthenticateBegin,
    WebAuthnAuthenticateComplete,
)

urls = [
    re_path(r'^credentials/$', WebAuthnCredentialList.as_view(), name='webauthn_credential_list'),
    re_path(r'^credentials/(?P<pk>[0-9]+)/$', WebAuthnCredentialDetail.as_view(), name='webauthn_credential_detail'),
    re_path(r'^register/begin/$', WebAuthnRegisterBegin.as_view(), name='webauthn_register_begin'),
    re_path(r'^register/complete/$', WebAuthnRegisterComplete.as_view(), name='webauthn_register_complete'),
    re_path(r'^authenticate/begin/$', WebAuthnAuthenticateBegin.as_view(), name='webauthn_authenticate_begin'),
    re_path(r'^authenticate/complete/$', WebAuthnAuthenticateComplete.as_view(), name='webauthn_authenticate_complete'),
]

__all__ = ['urls']
