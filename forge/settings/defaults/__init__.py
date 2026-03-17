# Copyright (c) 2015 Ansible, Inc.
# All Rights Reserved.

# Re-export all settings from domain modules.
# Import order matters: modules with cross-dependencies must come after their deps.

import copy
import os
import sys

from .base import *  # noqa: F401,F403
from .auth import *  # noqa: F401,F403
from .rest_api import *  # noqa: F401,F403
from .social_auth import *  # noqa: F401,F403
from .celery_conf import *  # noqa: F401,F403
from .jobs import *  # noqa: F401,F403
from .inventory_plugins import *  # noqa: F401,F403
from .websockets import *  # noqa: F401,F403
from .logging_conf import *  # noqa: F401,F403
from .forge_settings import *  # noqa: F401,F403

from split_settings.tools import include

# django-ansible-base
ANSIBLE_BASE_TEAM_MODEL = 'main.Team'
ANSIBLE_BASE_ORGANIZATION_MODEL = 'main.Organization'
ANSIBLE_BASE_RESOURCE_CONFIG_MODULE = 'forge.resource_api'
ANSIBLE_BASE_PERMISSION_MODEL = 'main.Permission'

from ansible_base.lib import dynamic_config  # noqa: E402

include(os.path.join(os.path.dirname(dynamic_config.__file__), 'dynamic_settings.py'))

# Add a postfix to the API URL patterns
# example if set to '' API pattern will be /api
# example if set to 'controller' API pattern will be /api AND /api/controller
OPTIONAL_API_URLPATTERN_PREFIX = ''

# Use AWX base view, to give 401 on unauthenticated requests
ANSIBLE_BASE_CUSTOM_VIEW_PARENT = 'forge.api.generics.APIView'

# Settings for the ansible_base RBAC system

# This has been moved to data migration code
ANSIBLE_BASE_ROLE_PRECREATE = {}

# Name for auto-created roles that give users permissions to what they create
ANSIBLE_BASE_ROLE_CREATOR_NAME = '{cls.__name__} Creator'

# Use the new Gateway RBAC system for evaluations? You should. We will remove the old system soon.
ANSIBLE_BASE_ROLE_SYSTEM_ACTIVATED = True

# Permissions a user will get when creating a new item
ANSIBLE_BASE_CREATOR_DEFAULTS = ['change', 'delete', 'execute', 'use', 'adhoc', 'approve', 'update', 'view']

# Temporary, for old roles API compatibility, save child permissions at organization level
ANSIBLE_BASE_CACHE_PARENT_PERMISSIONS = True

# Currently features are enabled to keep compatibility with old system, except custom roles
ANSIBLE_BASE_ALLOW_TEAM_ORG_ADMIN = False
# ANSIBLE_BASE_ALLOW_CUSTOM_ROLES = True
ANSIBLE_BASE_ALLOW_CUSTOM_TEAM_ROLES = False
ANSIBLE_BASE_ALLOW_SINGLETON_USER_ROLES = True
ANSIBLE_BASE_ALLOW_SINGLETON_TEAM_ROLES = False  # System auditor has always been restricted to users
ANSIBLE_BASE_ALLOW_SINGLETON_ROLES_API = False  # Do not allow creating user-defined system-wide roles

# system username for django-ansible-base
SYSTEM_USERNAME = None

# Store a snapshot of default settings at this point.
_this_module = sys.modules[__name__]
_local_vars = dir(_this_module)
DEFAULTS_SNAPSHOT = {}
for _setting in _local_vars:
    if _setting.isupper():
        DEFAULTS_SNAPSHOT[_setting] = copy.deepcopy(getattr(_this_module, _setting))

del _local_vars, _this_module, _setting
