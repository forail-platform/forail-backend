# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

# Authentication, session, CSRF, OAuth2, LDAP settings

import ldap


# Disallow sending session cookies over insecure connections
SESSION_COOKIE_SECURE = True

# Seconds before sessions expire.
# Note: This setting may be overridden by database settings.
SESSION_COOKIE_AGE = 1800

# Option to change userLoggedIn cookie SameSite policy.
USER_COOKIE_SAMESITE = 'Lax'

# Name of the cookie that contains the session information.
# Note: Changing this value may require changes to any clients.
SESSION_COOKIE_NAME = 'awx_sessionid'

# Maximum number of per-user valid, concurrent sessions.
# -1 is unlimited
# Note: This setting may be overridden by database settings.
SESSIONS_PER_USER = -1

CSRF_USE_SESSIONS = False

# Disallow sending csrf cookies over insecure connections
CSRF_COOKIE_SECURE = True

# Limit CSRF cookies to browser sessions
CSRF_COOKIE_AGE = None

AUTHENTICATION_BACKENDS = (
    'forail.sso.backends.LDAPBackend',
    'forail.sso.backends.LDAPBackend1',
    'forail.sso.backends.LDAPBackend2',
    'forail.sso.backends.LDAPBackend3',
    'forail.sso.backends.LDAPBackend4',
    'forail.sso.backends.LDAPBackend5',
    'forail.sso.backends.RADIUSBackend',
    'forail.sso.backends.TACACSPlusBackend',
    'social_core.backends.google.GoogleOAuth2',
    'social_core.backends.github.GithubOAuth2',
    'social_core.backends.github.GithubOrganizationOAuth2',
    'social_core.backends.github.GithubTeamOAuth2',
    'social_core.backends.github_enterprise.GithubEnterpriseOAuth2',
    'social_core.backends.github_enterprise.GithubEnterpriseOrganizationOAuth2',
    'social_core.backends.github_enterprise.GithubEnterpriseTeamOAuth2',
    'social_core.backends.open_id_connect.OpenIdConnectAuth',
    'social_core.backends.azuread.AzureADOAuth2',
    'forail.sso.backends.SAMLAuth',
    'forail.main.backends.AWXModelBackend',
)


# Django OAuth Toolkit settings
OAUTH2_PROVIDER_APPLICATION_MODEL = 'main.OAuth2Application'
OAUTH2_PROVIDER_ACCESS_TOKEN_MODEL = 'main.OAuth2AccessToken'
OAUTH2_PROVIDER_REFRESH_TOKEN_MODEL = 'oauth2_provider.RefreshToken'
OAUTH2_PROVIDER_ID_TOKEN_MODEL = "oauth2_provider.IDToken"

OAUTH2_PROVIDER = {'ACCESS_TOKEN_EXPIRE_SECONDS': 31536000000, 'AUTHORIZATION_CODE_EXPIRE_SECONDS': 600, 'REFRESH_TOKEN_EXPIRE_SECONDS': 2628000}
ALLOW_OAUTH2_FOR_EXTERNAL_USERS = False

# LDAP server (default to None to skip using LDAP authentication).
# Note: This setting may be overridden by database settings.
AUTH_LDAP_SERVER_URI = None

# Disable LDAP referrals by default (to prevent certain LDAP queries from
# hanging with AD).
# Note: This setting may be overridden by database settings.
AUTH_LDAP_CONNECTION_OPTIONS = {ldap.OPT_REFERRALS: 0, ldap.OPT_NETWORK_TIMEOUT: 30}

# Radius server settings (default to empty string to skip using Radius auth).
# Note: These settings may be overridden by database settings.
RADIUS_SERVER = ''
RADIUS_PORT = 1812
RADIUS_SECRET = ''

# TACACS+ settings (default host to empty string to skip using TACACS+ auth).
# Note: These settings may be overridden by database settings.
TACACSPLUS_HOST = ''
TACACSPLUS_PORT = 49
TACACSPLUS_SECRET = ''
TACACSPLUS_SESSION_TIMEOUT = 5
TACACSPLUS_AUTH_PROTOCOL = 'ascii'
TACACSPLUS_REM_ADDR = False

# Enable / Disable HTTP Basic Authentication used in the API browser
# Note: Session limits are not enforced when using HTTP Basic Authentication.
# Note: This setting may be overridden by database settings.
AUTH_BASIC_ENABLED = True

# If set, specifies a URL that unauthenticated users will be redirected to
# when trying to access a UI page that requries authentication.
LOGIN_REDIRECT_OVERRIDE = ''

# Note: This setting may be overridden by database settings.
ALLOW_METRICS_FOR_ANONYMOUS_USERS = False
