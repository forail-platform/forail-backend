import hashlib
import ipaddress
import json
import logging
import socket
import time
from urllib.parse import urlsplit

import requests
from django.apps import apps
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger('forail.main.services.dynamic_survey')

DYNAMIC_CHOICES_CACHE_PREFIX = 'dynamic_survey_choices_'

# Jinja2 as a choices source is a code-execution surface, not a formatting
# convenience: the template text is supplied by whoever may edit a job
# template's survey spec, and it is rendered inside the web process when any
# user with `start` permission opens the launch prompt. Rendering it through a
# plain Environment hands that user Python -- `{{ cycler.__init__.__globals__ }}`
# is the standard route from a template to the module table.
#
# So the source type is refused unless an operator turns it on, and the switch
# is a settings *file* value on purpose -- deliberately not a database-backed
# setting exposed over /api/v2/settings/. The same API surface used to plant a
# payload must not also be able to enable its execution.
SURVEY_DYNAMIC_CHOICES_JINJA2_SETTING = 'SURVEY_DYNAMIC_CHOICES_JINJA2_ENABLED'

# Filters left reachable when an operator does enable the source type. Jinja2
# seeds an environment with far more than a choices list needs; what is not
# here is removed rather than trusted to the sandbox.
JINJA2_ALLOWED_FILTERS = frozenset(
    {
        'batch',
        'default',
        'first',
        'int',
        'join',
        'last',
        'length',
        'list',
        'lower',
        'map',
        'reject',
        'replace',
        'reverse',
        'select',
        'sort',
        'string',
        'tojson',
        'trim',
        'unique',
        'upper',
    }
)

# Same ceiling the DB source applies, for the same reason: a choices list is a
# dropdown, not a data export.
MAX_CHOICES = 500

# The api_endpoint source makes the server issue a request to a URL taken from
# the survey. Without a destination policy that is an SSRF primitive: whoever
# edits a job template picks the address, and the server reaches it from inside
# the cluster -- cloud metadata endpoints, admin ports bound to loopback,
# neighbouring services -- while the JSON body comes back through the choices
# endpoint to any user with `start` permission.
#
# The destination must therefore be named by an operator, in a settings file,
# and it is host-exact: no wildcards, no suffix matching. An empty list (the
# default) disables the source type outright.
SURVEY_DYNAMIC_CHOICES_API_ALLOWLIST_SETTING = 'SURVEY_DYNAMIC_CHOICES_API_ALLOWLIST'

# Even an allowlisted name is re-checked after resolution, which is what stops an
# allowlisted host from being pointed at the metadata service. Private ranges are
# deliberately permitted: an on-prem CMDB on 10.0.0.0/8 is the ordinary case for
# this feature, and the operator naming the host is the trust decision. What is
# refused is the set no legitimate choices API lives on.
API_FORBIDDEN_MESSAGE = {
    'loopback': 'a loopback address',
    'link_local': 'a link-local address (this is where cloud metadata lives)',
    'multicast': 'a multicast address',
    'reserved': 'a reserved address',
    'unspecified': 'the unspecified address',
}

# A choices list that does not fit in a megabyte is not a choices list. Read
# bounded rather than trusting Content-Length, which the peer controls.
API_RESPONSE_MAX_BYTES = 1024 * 1024

# The survey supplies the timeout, so it needs a ceiling: a request that hangs
# holds a web worker for as long as it is allowed to.
API_MAX_TIMEOUT = 30


def _api_allowlist():
    hosts = getattr(settings, SURVEY_DYNAMIC_CHOICES_API_ALLOWLIST_SETTING, ()) or ()
    if isinstance(hosts, str):
        hosts = (hosts,)
    try:
        return {h.strip().lower() for h in hosts if isinstance(h, str) and h.strip()}
    except TypeError:
        return set()


def api_destination_refusal(url):
    """
    Why this URL may not be fetched, or None if it may.

    Returns a reason string rather than a bool so the caller can log which rule
    refused; the reason is deliberately not returned to the API client, since it
    would otherwise answer questions about the internal network.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return 'the URL cannot be parsed'

    if parts.scheme != 'https':
        return f"the scheme must be https, got {parts.scheme or 'none'}"

    host = parts.hostname
    if not host:
        return 'the URL has no host'

    allow = _api_allowlist()
    if not allow:
        return f'{SURVEY_DYNAMIC_CHOICES_API_ALLOWLIST_SETTING} is empty, so no destination is permitted'
    if host.lower() not in allow:
        return f'the host is not listed in {SURVEY_DYNAMIC_CHOICES_API_ALLOWLIST_SETTING}'

    try:
        infos = socket.getaddrinfo(host, parts.port or 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return 'the host does not resolve'

    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            return 'the host resolves to an address that cannot be parsed'
        for attribute, description in API_FORBIDDEN_MESSAGE.items():
            if getattr(addr, f'is_{attribute}', False):
                return f'the host resolves to {description}'
    return None


def jinja2_source_enabled():
    """
    Whether the jinja2 dynamic_choices source type may be used.

    The comparison is `is True` rather than a truth test on purpose: a stray
    string, a `1`, or a test double standing in for the settings object must
    not be enough to turn a code-execution path back on.
    """
    return getattr(settings, SURVEY_DYNAMIC_CHOICES_JINJA2_SETTING, False) is True
ALLOWED_DB_MODELS = {
    'hosts': ('main', 'Host'),
    'groups': ('main', 'Group'),
    'projects': ('main', 'Project'),
    'inventories': ('main', 'Inventory'),
    'credentials': ('main', 'Credential'),
    'organizations': ('main', 'Organization'),
    'execution_environments': ('main', 'ExecutionEnvironment'),
    'templates': ('main', 'JobTemplate'),
}

ALLOWED_DB_FIELDS = {'name', 'id', 'description'}


def _cache_key(question_variable, source_config, template):
    """
    Cache key for one question's resolved choices.

    The key must carry the scope the answer was resolved *in*, not just the
    question and its config. Two job templates can hold the same question with
    the same `dynamic_choices` block and different inventories -- or belong to
    different organizations -- and a key made of the variable name and a config
    hash alone is identical for both. The first request then fills the cache
    with one tenant's host names and the second is served them.

    Returns None when there is no template to scope by, which the caller treats
    as "do not cache" rather than "cache globally".
    """
    if template is None:
        return None

    scope = (
        getattr(template, 'pk', None),
        getattr(template, 'organization_id', None),
        getattr(template, 'inventory_id', None),
    )
    if scope[0] is None:
        return None

    digest = hashlib.sha256(
        json.dumps([question_variable, source_config, scope], sort_keys=True, default=str).encode()
    ).hexdigest()
    return f'{DYNAMIC_CHOICES_CACHE_PREFIX}{digest}'


def resolve_dynamic_choices(question, template=None):
    """
    Resolve dynamic choices for a single survey question.

    Returns a list of strings (choice values).
    """
    dc = question.get('dynamic_choices')
    if not dc or not dc.get('enabled'):
        return None

    source_type = dc.get('source_type')
    cache_ttl = dc.get('cache_ttl', 60)
    variable = question.get('variable', '')

    # Check cache
    ck = _cache_key(variable, dc, template)
    if ck is not None:
        cached = cache.get(ck)
        if cached is not None:
            return cached

    choices = []
    try:
        if source_type == 'db_query':
            choices = _resolve_db_query(dc, template)
        elif source_type == 'api_endpoint':
            choices = _resolve_api_endpoint(dc)
        elif source_type == 'jinja2':
            # Reached only by survey specs stored before the config validation
            # below started rejecting this source type. Refuse rather than
            # render: the payload is already in the database, and this is the
            # call that would execute it.
            if not jinja2_source_enabled():
                logger.warning(
                    'Refusing to render a jinja2 dynamic_choices template for survey variable %s: '
                    'the jinja2 source type is disabled (%s is not True). The stored survey spec '
                    'predates the validation that now rejects it.',
                    variable,
                    SURVEY_DYNAMIC_CHOICES_JINJA2_SETTING,
                )
                return []
            choices = _resolve_jinja2(dc, template)
        else:
            logger.warning('Unknown dynamic_choices source_type: %s', source_type)
            return []
    except Exception:
        logger.exception('Error resolving dynamic choices for variable %s', variable)
        return []

    # Ensure all choices are strings
    choices = [str(c) for c in choices]

    # Cache results
    if ck is not None and cache_ttl and cache_ttl > 0:
        cache.set(ck, choices, timeout=cache_ttl)

    return choices


def _resolve_db_query(dc, template=None):
    """
    Resolve choices from a database query.

    Config format:
    {
        "model": "hosts",          # key from ALLOWED_DB_MODELS
        "field": "name",           # field to use as choice value
        "filter": {                # optional filter kwargs
            "inventory__id": 1
        }
    }
    """
    model_key = dc.get('model', '')
    field = dc.get('field', 'name')
    filter_kwargs = dc.get('filter', {})

    if model_key not in ALLOWED_DB_MODELS:
        logger.warning('Dynamic choices: model %s not in allowed list', model_key)
        return []

    if field not in ALLOWED_DB_FIELDS:
        logger.warning('Dynamic choices: field %s not in allowed list', field)
        return []

    app_label, model_name = ALLOWED_DB_MODELS[model_key]
    Model = apps.get_model(app_label, model_name)

    # Sanitize filter kwargs — only allow safe lookups
    safe_kwargs = {}
    for key, value in filter_kwargs.items():
        parts = key.split('__')
        base_field = parts[0]
        # Allow filtering on common safe fields
        if base_field in ('id', 'name', 'inventory', 'organization', 'project', 'inventory_id', 'organization_id', 'project_id'):
            safe_kwargs[key] = value

    # If template has an inventory, allow implicit filtering
    if not safe_kwargs and template and model_key in ('hosts', 'groups'):
        inventory_id = getattr(template, 'inventory_id', None)
        if inventory_id:
            safe_kwargs['inventory__id'] = inventory_id

    try:
        qs = Model.objects.filter(**safe_kwargs).values_list(field, flat=True).distinct().order_by(field)[:500]
        return list(qs)
    except Exception:
        logger.exception('Dynamic choices DB query failed for model %s', model_key)
        return []


def _resolve_api_endpoint(dc):
    """
    Resolve choices from an external API endpoint.

    Config format:
    {
        "url": "https://api.example.com/options",
        "method": "GET",
        "headers": {"Authorization": "Bearer xxx"},   # optional
        "json_path": "data.items",                     # optional dot-notation path to array
        "value_field": "name",                         # optional field to extract from objects
        "timeout": 10                                  # optional, default 10s
    }
    """
    url = dc.get('url', '')
    if not url:
        return []

    refusal = api_destination_refusal(url)
    if refusal:
        # Logged, not returned: the reason describes the internal network, and
        # the caller of the choices endpoint is any user with `start` permission.
        logger.warning('Refusing dynamic choices API request to %s: %s', url, refusal)
        return []

    method = dc.get('method', 'GET').upper()
    if method not in ('GET', 'POST'):
        logger.warning('Refusing dynamic choices API request to %s: method %s is not allowed', url, method)
        return []

    headers = dc.get('headers', {})
    timeout = dc.get('timeout', 10)
    try:
        timeout = min(float(timeout), API_MAX_TIMEOUT)
    except (TypeError, ValueError):
        timeout = 10
    json_path = dc.get('json_path', '')
    value_field = dc.get('value_field', '')

    try:
        # allow_redirects=False on purpose. Following them would re-open exactly
        # what api_destination_refusal() just closed: the first hop is checked,
        # every hop after it is chosen by the peer.
        kwargs = dict(headers=headers, timeout=timeout, allow_redirects=False, stream=True)
        if method == 'POST':
            resp = requests.post(url, json=dc.get('body', {}), **kwargs)
        else:
            resp = requests.get(url, **kwargs)

        with resp:
            if resp.is_redirect or resp.is_permanent_redirect:
                logger.warning(
                    'Refusing dynamic choices API response from %s: redirect to %s not followed',
                    url,
                    resp.headers.get('Location', '(no Location)'),
                )
                return []
            resp.raise_for_status()

            # Read bounded rather than trusting Content-Length: the peer sets it.
            body = resp.raw.read(API_RESPONSE_MAX_BYTES + 1, decode_content=True)
            if len(body) > API_RESPONSE_MAX_BYTES:
                logger.warning('Refusing dynamic choices API response from %s: larger than %s bytes', url, API_RESPONSE_MAX_BYTES)
                return []
            data = json.loads(body)
    except Exception:
        logger.exception('Dynamic choices API request failed for %s', url)
        return []

    # Navigate JSON path
    if json_path:
        for key in json_path.split('.'):
            if isinstance(data, dict):
                data = data.get(key, [])
            elif isinstance(data, list) and key.isdigit():
                data = data[int(key)]
            else:
                return []

    if not isinstance(data, list):
        return []

    # Extract values
    if value_field:
        return [item.get(value_field, '') for item in data if isinstance(item, dict)][:MAX_CHOICES]
    else:
        return [str(item) for item in data][:MAX_CHOICES]


def _resolve_jinja2(dc, template=None):
    """
    Resolve choices from a Jinja2 template expression.

    Disabled unless ``SURVEY_DYNAMIC_CHOICES_JINJA2_ENABLED`` is True in the
    server settings file; see the note on that setting above. When it is on,
    the template is rendered in a sandbox with the globals removed and the
    filter set reduced to ``JINJA2_ALLOWED_FILTERS``.

    Even then the sandbox is a hardening measure, not a trust boundary --
    sandbox escapes are found periodically, and a template that renders in the
    web process is worth an escape to whoever plants it. Prefer db_query or
    api_endpoint.

    Config format:
    {
        "template": "{{ groups | sort | tojson }}"
    }

    Available context variables:
    - hosts: list of host names from the template's inventory
    - groups: list of group names from the template's inventory
    """
    if not jinja2_source_enabled():
        logger.warning(
            'Refusing to render a jinja2 dynamic_choices template: the jinja2 source type '
            'is disabled (%s is not True).',
            SURVEY_DYNAMIC_CHOICES_JINJA2_SETTING,
        )
        return []

    try:
        from jinja2 import BaseLoader, StrictUndefined
        from jinja2.sandbox import SandboxedEnvironment
    except ImportError:
        logger.error('Jinja2 is required for dynamic_choices jinja2 source_type')
        return []

    template_str = dc.get('template', '')
    if not template_str:
        return []

    # Build context
    context = {}
    if template:
        inventory_id = getattr(template, 'inventory_id', None)
        if inventory_id:
            Host = apps.get_model('main', 'Host')
            Group = apps.get_model('main', 'Group')
            context['hosts'] = list(Host.objects.filter(inventory_id=inventory_id).values_list('name', flat=True)[:500])
            context['groups'] = list(Group.objects.filter(inventory_id=inventory_id).values_list('name', flat=True)[:500])

    try:
        env = SandboxedEnvironment(loader=BaseLoader(), undefined=StrictUndefined)
        # Jinja2 seeds every environment with range, dict, lipsum, cycler,
        # namespace and joiner. cycler and joiner are class instances, which is
        # exactly what `{{ cycler.__init__.__globals__.os }}` walks. The sandbox
        # blocks that attribute access; there is still no reason to leave the
        # objects reachable.
        env.globals.clear()
        env.filters = {name: f for name, f in env.filters.items() if name in JINJA2_ALLOWED_FILTERS}
        env.tests = {}

        tmpl = env.from_string(template_str)
        result = tmpl.render(**context)

        # Try to parse as JSON list
        parsed = json.loads(result)
        if isinstance(parsed, list):
            return parsed[:MAX_CHOICES]
        return []
    except Exception:
        logger.exception('Dynamic choices Jinja2 evaluation failed')
        return []


def validate_dynamic_choices_config(dc):
    """
    Validate the dynamic_choices configuration on a survey question.
    Returns a list of error strings (empty = valid).
    """
    errors = []

    if not isinstance(dc, dict):
        errors.append("dynamic_choices must be a dictionary.")
        return errors

    if 'enabled' not in dc:
        errors.append("dynamic_choices must have an 'enabled' field.")
        return errors

    if not dc.get('enabled'):
        return errors

    source_type = dc.get('source_type', '')
    if source_type not in ('db_query', 'api_endpoint', 'jinja2'):
        errors.append(f"dynamic_choices source_type must be one of: db_query, api_endpoint, jinja2. Got '{source_type}'.")
        return errors

    if source_type == 'jinja2' and not jinja2_source_enabled():
        errors.append(
            "dynamic_choices source_type 'jinja2' is disabled: it renders a template supplied "
            "with the survey inside the server process. Use db_query or api_endpoint, or ask an "
            "administrator to set SURVEY_DYNAMIC_CHOICES_JINJA2_ENABLED = True in the server "
            "settings file."
        )
        return errors

    cache_ttl = dc.get('cache_ttl', 60)
    if not isinstance(cache_ttl, int) or cache_ttl < 0:
        errors.append("dynamic_choices cache_ttl must be a non-negative integer.")

    if source_type == 'db_query':
        model = dc.get('model', '')
        if model not in ALLOWED_DB_MODELS:
            errors.append(f"dynamic_choices model must be one of: {', '.join(ALLOWED_DB_MODELS.keys())}. Got '{model}'.")
        field = dc.get('field', 'name')
        if field not in ALLOWED_DB_FIELDS:
            errors.append(f"dynamic_choices field must be one of: {', '.join(ALLOWED_DB_FIELDS)}. Got '{field}'.")

    elif source_type == 'api_endpoint':
        url = dc.get('url', '')
        if not url or not isinstance(url, str):
            errors.append("dynamic_choices api_endpoint requires a non-empty 'url' string.")
        else:
            # Refuse at save time as well as at fetch time, so the editor learns
            # the destination is not permitted instead of getting a survey that
            # silently resolves to nothing.
            refusal = api_destination_refusal(url)
            if refusal:
                errors.append(
                    "dynamic_choices api_endpoint url is not permitted: "
                    f"{refusal}. Destinations are named by an administrator in "
                    f"{SURVEY_DYNAMIC_CHOICES_API_ALLOWLIST_SETTING}."
                )

    elif source_type == 'jinja2':
        tmpl = dc.get('template', '')
        if not tmpl or not isinstance(tmpl, str):
            errors.append("dynamic_choices jinja2 requires a non-empty 'template' string.")

    return errors


def survey_choice_list(question, template=None):
    """
    The permitted values for a choice question, and whether they are dynamic.

    For a dynamic question this resolves the list at the moment it is asked for
    -- which, on the launch path, is the point of the exercise. Validation there
    used to be skipped with the comment "validated at resolve time", but the
    resolve endpoint only hands options to the UI; nothing on the launch path
    ever compared the submitted value against them, so a direct API client could
    pass any extra_var for a question that presents as a fixed dropdown.

    A failed resolution yields an empty list, and an empty list rejects every
    answer. That is deliberate: if the permitted values cannot be determined, the
    request cannot be validated, and accepting it would mean trusting the caller
    for exactly the field this check constrains. The choices could not have been
    offered in the UI either.
    """
    dc = question.get('dynamic_choices') or {}
    if dc.get('enabled'):
        try:
            resolved = resolve_dynamic_choices(question, template=template)
        except Exception:
            logger.exception('Failed to resolve dynamic choices for survey variable %s', question.get('variable'))
            resolved = None
        return list(resolved or []), True

    choices = question.get('choices', [])
    if isinstance(choices, str):
        choices = [choice for choice in choices.splitlines() if choice.strip() != '']
    return list(choices), False


def choice_error_message(question, value, choices, is_dynamic):
    """The message for a value that is not among a question's permitted ones."""
    variable = question.get('variable')
    if not is_dynamic:
        return "Value %s for '%s' expected to be one of %s." % (value, variable, choices)
    if not choices:
        # Distinguish "resolved to nothing" from "not in the list". The first is
        # usually a broken source, and reporting it as a bad answer sends the
        # operator looking in the wrong place.
        return "Value %s for '%s' could not be validated: its dynamic choices resolved to no options." % (value, variable)
    # The list can hold up to MAX_CHOICES entries, so it is counted, not printed.
    return "Value %s for '%s' expected to be one of its %s dynamic choices." % (value, variable, len(choices))
