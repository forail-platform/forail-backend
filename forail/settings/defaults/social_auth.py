# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

# Social auth providers and pipeline configuration

# Social Auth configuration.
SOCIAL_AUTH_STRATEGY = 'social_django.strategy.DjangoStrategy'
SOCIAL_AUTH_STORAGE = 'social_django.models.DjangoStorage'
SOCIAL_AUTH_USER_MODEL = 'auth.User'
ROLE_SINGLETON_USER_RELATIONSHIP = ''
ROLE_SINGLETON_TEAM_RELATIONSHIP = ''

# We want to short-circuit RBAC methods to get permission to system admins and auditors
ROLE_BYPASS_SUPERUSER_FLAGS = ['is_superuser']
ROLE_BYPASS_ACTION_FLAGS = {'view': 'is_system_auditor'}

_SOCIAL_AUTH_PIPELINE_BASE = (
    'social_core.pipeline.social_auth.social_details',
    'social_core.pipeline.social_auth.social_uid',
    'social_core.pipeline.social_auth.auth_allowed',
    'social_core.pipeline.social_auth.social_user',
    'social_core.pipeline.user.get_username',
    'social_core.pipeline.social_auth.associate_by_email',
    'social_core.pipeline.user.create_user',
    'forail.sso.social_base_pipeline.check_user_found_or_created',
    'social_core.pipeline.social_auth.associate_user',
    'social_core.pipeline.social_auth.load_extra_data',
    'forail.sso.social_base_pipeline.set_is_active_for_new_user',
    'social_core.pipeline.user.user_details',
    'forail.sso.social_base_pipeline.prevent_inactive_login',
)
SOCIAL_AUTH_PIPELINE = _SOCIAL_AUTH_PIPELINE_BASE + ('forail.sso.social_pipeline.update_user_orgs', 'forail.sso.social_pipeline.update_user_teams')
SOCIAL_AUTH_SAML_PIPELINE = _SOCIAL_AUTH_PIPELINE_BASE + ('forail.sso.saml_pipeline.populate_user', 'forail.sso.saml_pipeline.update_user_flags')
SAML_AUTO_CREATE_OBJECTS = True

SOCIAL_AUTH_LOGIN_URL = '/'
SOCIAL_AUTH_LOGIN_REDIRECT_URL = '/sso/complete/'
SOCIAL_AUTH_LOGIN_ERROR_URL = '/sso/error/'
SOCIAL_AUTH_INACTIVE_USER_URL = '/sso/inactive/'

SOCIAL_AUTH_RAISE_EXCEPTIONS = False
SOCIAL_AUTH_USERNAME_IS_FULL_EMAIL = False
# SOCIAL_AUTH_SLUGIFY_USERNAMES = True
SOCIAL_AUTH_CLEAN_USERNAMES = True

SOCIAL_AUTH_SANITIZE_REDIRECTS = True
SOCIAL_AUTH_REDIRECT_IS_HTTPS = False

# Note: These settings may be overridden by database settings.
SOCIAL_AUTH_GOOGLE_OAUTH2_KEY = ''
SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET = ''
SOCIAL_AUTH_GOOGLE_OAUTH2_SCOPE = ['profile']

SOCIAL_AUTH_GITHUB_KEY = ''
SOCIAL_AUTH_GITHUB_SECRET = ''
SOCIAL_AUTH_GITHUB_SCOPE = ['user:email', 'read:org']

SOCIAL_AUTH_GITHUB_ORG_KEY = ''
SOCIAL_AUTH_GITHUB_ORG_SECRET = ''
SOCIAL_AUTH_GITHUB_ORG_NAME = ''
SOCIAL_AUTH_GITHUB_ORG_SCOPE = ['user:email', 'read:org']

SOCIAL_AUTH_GITHUB_TEAM_KEY = ''
SOCIAL_AUTH_GITHUB_TEAM_SECRET = ''
SOCIAL_AUTH_GITHUB_TEAM_ID = ''
SOCIAL_AUTH_GITHUB_TEAM_SCOPE = ['user:email', 'read:org']

SOCIAL_AUTH_GITHUB_ENTERPRISE_KEY = ''
SOCIAL_AUTH_GITHUB_ENTERPRISE_SECRET = ''
SOCIAL_AUTH_GITHUB_ENTERPRISE_SCOPE = ['user:email', 'read:org']

SOCIAL_AUTH_GITHUB_ENTERPRISE_ORG_KEY = ''
SOCIAL_AUTH_GITHUB_ENTERPRISE_ORG_SECRET = ''
SOCIAL_AUTH_GITHUB_ENTERPRISE_ORG_NAME = ''
SOCIAL_AUTH_GITHUB_ENTERPRISE_ORG_SCOPE = ['user:email', 'read:org']

SOCIAL_AUTH_GITHUB_ENTERPRISE_TEAM_KEY = ''
SOCIAL_AUTH_GITHUB_ENTERPRISE_TEAM_SECRET = ''
SOCIAL_AUTH_GITHUB_ENTERPRISE_TEAM_ID = ''
SOCIAL_AUTH_GITHUB_ENTERPRISE_TEAM_SCOPE = ['user:email', 'read:org']

SOCIAL_AUTH_AZUREAD_OAUTH2_KEY = ''
SOCIAL_AUTH_AZUREAD_OAUTH2_SECRET = ''

SOCIAL_AUTH_SAML_SP_ENTITY_ID = ''
SOCIAL_AUTH_SAML_SP_PUBLIC_CERT = ''
SOCIAL_AUTH_SAML_SP_PRIVATE_KEY = ''
SOCIAL_AUTH_SAML_ORG_INFO = {}
SOCIAL_AUTH_SAML_TECHNICAL_CONTACT = {}
SOCIAL_AUTH_SAML_SUPPORT_CONTACT = {}
SOCIAL_AUTH_SAML_ENABLED_IDPS = {}

SOCIAL_AUTH_SAML_ORGANIZATION_ATTR = {}
SOCIAL_AUTH_SAML_TEAM_ATTR = {}
SOCIAL_AUTH_SAML_USER_FLAGS_BY_ATTR = {}
