"""
Standalone tests for dynamic survey service.
These tests do not require Django setup — they mock all Django dependencies.
"""
import json
import sys
import os
from unittest.mock import patch, MagicMock, PropertyMock

# Mock Django modules before importing our code.
#
# django.db has to be stubbed alongside the rest: forail/__init__.py does
# `from django.db import connection` at import time, and a bare MagicMock under
# 'django' is not a package, so that line is what used to make this file
# uncollectable on its own. It was excluded from CI for it.
sys.modules['django'] = MagicMock()
sys.modules['django.apps'] = MagicMock()
sys.modules['django.core'] = MagicMock()
sys.modules['django.core.cache'] = MagicMock()
sys.modules['django.conf'] = MagicMock()
sys.modules['django.db'] = MagicMock()

import pytest

# Now we can import after mocking Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Re-import with fresh mocks
if 'forail.main.services.dynamic_survey' in sys.modules:
    del sys.modules['forail.main.services.dynamic_survey']

from forail.main.services import dynamic_survey
from forail.main.services.dynamic_survey import (
    validate_dynamic_choices_config,
    _resolve_api_endpoint,
    _resolve_jinja2,
    _resolve_db_query,
    resolve_dynamic_choices,
    ALLOWED_DB_MODELS,
    ALLOWED_DB_FIELDS,
)


class _Settings:
    """Stands in for django.conf.settings.

    The real settings object is a MagicMock here, and every attribute of a
    MagicMock is truthy -- which would silently enable the jinja2 source type
    in every test. The service reads the flag with `is True` for that reason;
    this class lets a test say which value it wants.
    """

    def __init__(self, **attrs):
        self.__dict__.update(attrs)


def jinja2_enabled(value=True):
    """Patch the service's settings so the jinja2 source type is on/off."""
    return patch.object(
        dynamic_survey, 'settings', _Settings(SURVEY_DYNAMIC_CHOICES_JINJA2_ENABLED=value)
    )


def api_allowed(*hosts):
    """Patch the service's settings so those hosts are permitted destinations."""
    return patch.object(
        dynamic_survey, 'settings', _Settings(SURVEY_DYNAMIC_CHOICES_API_ALLOWLIST=list(hosts))
    )


def resolves_to(address='93.184.216.34'):
    """Patch name resolution, so no test depends on a real DNS answer."""
    family = 2 if ':' not in address else 10
    return patch.object(
        dynamic_survey,
        'socket',
        MagicMock(
            IPPROTO_TCP=6,
            getaddrinfo=MagicMock(return_value=[(family, 1, 6, '', (address, 443))]),
        ),
    )


def fake_template(pk=1, organization_id=1, inventory_id=1):
    """A job template, as the cache key reads it."""
    t = MagicMock()
    t.pk = pk
    t.organization_id = organization_id
    t.inventory_id = inventory_id
    return t


def api_response(payload, status_ok=True):
    """A stand-in for requests' Response, as the fetch path actually uses it."""
    resp = MagicMock()
    resp.is_redirect = False
    resp.is_permanent_redirect = False
    resp.headers = {}
    resp.raw.read.return_value = json.dumps(payload).encode()
    resp.raise_for_status = MagicMock() if status_ok else MagicMock(side_effect=Exception('http error'))
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


# ===== validate_dynamic_choices_config =====

class TestValidation:

    def test_valid_db_query(self):
        dc = {'enabled': True, 'source_type': 'db_query', 'model': 'hosts', 'field': 'name', 'cache_ttl': 60}
        assert validate_dynamic_choices_config(dc) == []

    def test_valid_api_endpoint(self):
        dc = {'enabled': True, 'source_type': 'api_endpoint', 'url': 'https://example.com/api', 'cache_ttl': 30}
        with api_allowed('example.com'), resolves_to():
            assert validate_dynamic_choices_config(dc) == []

    def test_api_endpoint_rejected_without_an_allowlist(self):
        # Same posture as the jinja2 source type: nothing is reachable until an
        # operator names it.
        dc = {'enabled': True, 'source_type': 'api_endpoint', 'url': 'https://example.com/api', 'cache_ttl': 30}
        errors = validate_dynamic_choices_config(dc)
        assert any('SURVEY_DYNAMIC_CHOICES_API_ALLOWLIST' in e for e in errors)

    def test_jinja2_rejected_by_default(self):
        # The source type executes a template in the web process, so a survey
        # spec may not even be saved with it unless an operator opted in.
        dc = {'enabled': True, 'source_type': 'jinja2', 'template': '{{ hosts }}', 'cache_ttl': 10}
        errors = validate_dynamic_choices_config(dc)
        assert len(errors) == 1
        assert 'SURVEY_DYNAMIC_CHOICES_JINJA2_ENABLED' in errors[0]

    def test_valid_jinja2_when_operator_enabled(self):
        dc = {'enabled': True, 'source_type': 'jinja2', 'template': '{{ hosts }}', 'cache_ttl': 10}
        with jinja2_enabled():
            assert validate_dynamic_choices_config(dc) == []

    def test_jinja2_not_enabled_by_a_truthy_value(self):
        # A stray "true"/1 in a settings file must not turn code execution on.
        dc = {'enabled': True, 'source_type': 'jinja2', 'template': '{{ hosts }}'}
        for value in ('True', 'true', 1, [1]):
            with jinja2_enabled(value):
                errors = validate_dynamic_choices_config(dc)
                assert errors, f'{value!r} should not enable the jinja2 source type'

    def test_disabled_always_valid(self):
        assert validate_dynamic_choices_config({'enabled': False}) == []

    def test_not_dict(self):
        errors = validate_dynamic_choices_config("bad")
        assert len(errors) == 1
        assert "dictionary" in errors[0]

    def test_missing_enabled(self):
        errors = validate_dynamic_choices_config({'source_type': 'db_query'})
        assert len(errors) == 1
        assert "'enabled'" in errors[0]

    def test_bad_source_type(self):
        errors = validate_dynamic_choices_config({'enabled': True, 'source_type': 'magic'})
        assert len(errors) == 1
        assert "source_type" in errors[0]

    def test_invalid_model(self):
        dc = {'enabled': True, 'source_type': 'db_query', 'model': 'users'}
        errors = validate_dynamic_choices_config(dc)
        assert any("model" in e for e in errors)

    def test_invalid_field(self):
        dc = {'enabled': True, 'source_type': 'db_query', 'model': 'hosts', 'field': 'secret'}
        errors = validate_dynamic_choices_config(dc)
        assert any("field" in e for e in errors)

    def test_api_missing_url(self):
        dc = {'enabled': True, 'source_type': 'api_endpoint'}
        errors = validate_dynamic_choices_config(dc)
        assert any("url" in e for e in errors)

    def test_jinja2_missing_template(self):
        dc = {'enabled': True, 'source_type': 'jinja2'}
        with jinja2_enabled():
            errors = validate_dynamic_choices_config(dc)
        assert any("template" in e for e in errors)

    def test_negative_ttl(self):
        dc = {'enabled': True, 'source_type': 'db_query', 'model': 'hosts', 'cache_ttl': -5}
        errors = validate_dynamic_choices_config(dc)
        assert any("cache_ttl" in e for e in errors)

    def test_all_allowed_models(self):
        for model in ALLOWED_DB_MODELS:
            dc = {'enabled': True, 'source_type': 'db_query', 'model': model}
            errors = validate_dynamic_choices_config(dc)
            assert not any("model" in e for e in errors), f"Model '{model}' should be allowed"

    def test_all_allowed_fields(self):
        for field in ALLOWED_DB_FIELDS:
            dc = {'enabled': True, 'source_type': 'db_query', 'model': 'hosts', 'field': field}
            errors = validate_dynamic_choices_config(dc)
            assert not any("field" in e for e in errors), f"Field '{field}' should be allowed"


# ===== _resolve_api_endpoint =====

class TestApiEndpoint:
    """The fetch path, with the destination named by an operator."""

    @patch('forail.main.services.dynamic_survey.requests')
    def test_simple_list(self, mock_req):
        mock_req.get.return_value = api_response(['a', 'b', 'c'])
        with api_allowed('example.com'), resolves_to():
            result = _resolve_api_endpoint({'url': 'https://example.com/list'})
        assert result == ['a', 'b', 'c']

    @patch('forail.main.services.dynamic_survey.requests')
    def test_json_path(self, mock_req):
        mock_req.get.return_value = api_response({'data': {'items': ['x', 'y']}})
        with api_allowed('example.com'), resolves_to():
            result = _resolve_api_endpoint({'url': 'https://example.com', 'json_path': 'data.items'})
        assert result == ['x', 'y']

    @patch('forail.main.services.dynamic_survey.requests')
    def test_value_field(self, mock_req):
        mock_req.get.return_value = api_response([{'name': 'srv1'}, {'name': 'srv2'}])
        with api_allowed('example.com'), resolves_to():
            result = _resolve_api_endpoint({'url': 'https://example.com', 'value_field': 'name'})
        assert result == ['srv1', 'srv2']

    @patch('forail.main.services.dynamic_survey.requests')
    def test_post_method(self, mock_req):
        mock_req.post.return_value = api_response(['p1', 'p2'])
        with api_allowed('example.com'), resolves_to():
            result = _resolve_api_endpoint({'url': 'https://example.com', 'method': 'POST', 'body': {}})
        assert result == ['p1', 'p2']
        mock_req.post.assert_called_once()

    def test_empty_url(self):
        assert _resolve_api_endpoint({'url': ''}) == []

    @patch('forail.main.services.dynamic_survey.requests')
    def test_error_returns_empty(self, mock_req):
        mock_req.get.side_effect = Exception("fail")
        with api_allowed('bad.example.com'), resolves_to():
            assert _resolve_api_endpoint({'url': 'https://bad.example.com'}) == []

    @patch('forail.main.services.dynamic_survey.requests')
    def test_non_list_response(self, mock_req):
        mock_req.get.return_value = api_response({"not": "a list"})
        with api_allowed('example.com'), resolves_to():
            result = _resolve_api_endpoint({'url': 'https://example.com'})
        assert result == []

    @patch('forail.main.services.dynamic_survey.requests')
    def test_redirect_is_not_followed(self, mock_req):
        # The first hop is what the allowlist checked; every hop after it is
        # chosen by the peer, so following one re-opens the SSRF.
        resp = api_response([])
        resp.is_redirect = True
        resp.headers = {'Location': 'http://169.254.169.254/latest/meta-data/'}
        mock_req.get.return_value = resp
        with api_allowed('example.com'), resolves_to():
            assert _resolve_api_endpoint({'url': 'https://example.com'}) == []
        assert mock_req.get.call_args[1]['allow_redirects'] is False

    @patch('forail.main.services.dynamic_survey.requests')
    def test_oversized_response_is_refused(self, mock_req):
        resp = api_response([])
        resp.raw.read.return_value = b'x' * (dynamic_survey.API_RESPONSE_MAX_BYTES + 1)
        mock_req.get.return_value = resp
        with api_allowed('example.com'), resolves_to():
            assert _resolve_api_endpoint({'url': 'https://example.com'}) == []

    @patch('forail.main.services.dynamic_survey.requests')
    def test_timeout_is_capped(self, mock_req):
        mock_req.get.return_value = api_response([])
        with api_allowed('example.com'), resolves_to():
            _resolve_api_endpoint({'url': 'https://example.com', 'timeout': 9999})
        assert mock_req.get.call_args[1]['timeout'] == dynamic_survey.API_MAX_TIMEOUT


class TestApiDestinationPolicy:
    """
    Destination control, which is what turns this source type from an SSRF
    primitive into a fetch from somewhere an operator named.
    """

    @patch('forail.main.services.dynamic_survey.requests')
    def test_no_allowlist_refuses_everything(self, mock_req):
        # The default posture: the source type is off until an operator names a
        # destination.
        assert _resolve_api_endpoint({'url': 'https://example.com'}) == []
        mock_req.get.assert_not_called()

    @patch('forail.main.services.dynamic_survey.requests')
    def test_unlisted_host_is_refused(self, mock_req):
        with api_allowed('cmdb.internal.example.com'), resolves_to():
            assert _resolve_api_endpoint({'url': 'https://evil.example.net/x'}) == []
        mock_req.get.assert_not_called()

    @patch('forail.main.services.dynamic_survey.requests')
    def test_http_is_refused(self, mock_req):
        with api_allowed('example.com'), resolves_to():
            assert _resolve_api_endpoint({'url': 'http://example.com'}) == []
        mock_req.get.assert_not_called()

    @patch('forail.main.services.dynamic_survey.requests')
    def test_listed_host_resolving_to_metadata_is_refused(self, mock_req):
        # The case the allowlist alone does not cover: a listed name whose DNS
        # answer points at the cloud metadata service.
        with api_allowed('cmdb.internal.example.com'), resolves_to('169.254.169.254'):
            assert _resolve_api_endpoint({'url': 'https://cmdb.internal.example.com/x'}) == []
        mock_req.get.assert_not_called()

    @patch('forail.main.services.dynamic_survey.requests')
    def test_listed_host_resolving_to_loopback_is_refused(self, mock_req):
        with api_allowed('cmdb.internal.example.com'), resolves_to('127.0.0.1'):
            assert _resolve_api_endpoint({'url': 'https://cmdb.internal.example.com/x'}) == []
        mock_req.get.assert_not_called()

    @patch('forail.main.services.dynamic_survey.requests')
    def test_private_address_is_allowed(self, mock_req):
        # An on-prem CMDB on RFC1918 is the ordinary use of this feature; the
        # operator naming the host is the trust decision.
        mock_req.get.return_value = api_response(['srv1'])
        with api_allowed('cmdb.internal.example.com'), resolves_to('10.4.1.7'):
            assert _resolve_api_endpoint({'url': 'https://cmdb.internal.example.com/x'}) == ['srv1']

    @patch('forail.main.services.dynamic_survey.requests')
    def test_non_get_post_method_is_refused(self, mock_req):
        with api_allowed('example.com'), resolves_to():
            assert _resolve_api_endpoint({'url': 'https://example.com', 'method': 'DELETE'}) == []

    def test_validation_refuses_an_unlisted_destination(self):
        dc = {'enabled': True, 'source_type': 'api_endpoint', 'url': 'https://evil.example.net'}
        with api_allowed('cmdb.internal.example.com'), resolves_to():
            errors = validate_dynamic_choices_config(dc)
        assert any('not permitted' in e for e in errors)

    def test_validation_accepts_a_listed_destination(self):
        dc = {'enabled': True, 'source_type': 'api_endpoint', 'url': 'https://cmdb.internal.example.com/x'}
        with api_allowed('cmdb.internal.example.com'), resolves_to('10.4.1.7'):
            assert validate_dynamic_choices_config(dc) == []


# ===== _resolve_jinja2 =====

class TestJinja2:
    """The renderer, with the source type turned on by an operator."""

    def test_static_list(self):
        with jinja2_enabled():
            result = _resolve_jinja2({'template': '["opt1", "opt2"]'})
        assert result == ['opt1', 'opt2']

    def test_empty_template(self):
        with jinja2_enabled():
            assert _resolve_jinja2({'template': ''}) == []

    def test_invalid_output(self):
        # Non-JSON result
        with jinja2_enabled():
            result = _resolve_jinja2({'template': 'not json'})
        assert result == []

    def test_filters_still_work(self):
        with jinja2_enabled():
            result = _resolve_jinja2({'template': '{{ ["b", "a", "b"] | unique | sort | list | tojson }}'})
        assert result == ['a', 'b']

    def test_result_is_capped(self):
        with jinja2_enabled():
            result = _resolve_jinja2({'template': '{{ (["x"] * 600) | list | tojson }}'})
        assert len(result) == 500


class TestJinja2Disabled:
    """Default posture: the template is never rendered at all."""

    def test_renderer_refuses(self):
        # A template that would raise if it were rendered proves the renderer
        # was never reached, not merely that the output was discarded.
        assert _resolve_jinja2({'template': '["ran"]'}) == []

    @patch('forail.main.services.dynamic_survey.cache')
    @patch('forail.main.services.dynamic_survey._resolve_jinja2')
    def test_dispatch_does_not_call_the_renderer(self, mock_jinja, mock_cache):
        # Survey specs saved before the source type was refused still sit in the
        # database; resolving one must not execute it.
        mock_cache.get.return_value = None
        q = {
            'variable': 'v',
            'dynamic_choices': {
                'enabled': True,
                'source_type': 'jinja2',
                'template': '{{ cycler.__init__.__globals__ }}',
                'cache_ttl': 10,
            },
        }
        assert resolve_dynamic_choices(q) == []
        mock_jinja.assert_not_called()

    @patch('forail.main.services.dynamic_survey.cache')
    @patch('forail.main.services.dynamic_survey._resolve_jinja2')
    def test_refusal_is_not_cached(self, mock_jinja, mock_cache):
        # Caching the empty result would mask the warning for the whole TTL.
        mock_cache.get.return_value = None
        q = {'variable': 'v', 'dynamic_choices': {'enabled': True, 'source_type': 'jinja2', 'cache_ttl': 300}}
        resolve_dynamic_choices(q)
        mock_cache.set.assert_not_called()


# Known template-to-Python routes. These are the expressions the original
# unsandboxed Environment answered: `{{ cycler.__init__.__globals__.os.name }}`
# returned `posix`, which is a read from the module table and one attribute away
# from `os.system`.
JINJA2_ESCAPES = [
    "{{ cycler.__init__.__globals__.os.name }}",
    "{{ cycler.__init__.__globals__['os'].name }}",
    "{{ joiner.__init__.__globals__ }}",
    "{{ namespace.__init__.__globals__ }}",
    "{{ ''.__class__.__mro__[1].__subclasses__() }}",
    "{{ ''.__class__.__base__.__subclasses__() }}",
    "{{ [].__class__.__base__.__subclasses__() }}",
    "{{ lipsum.__globals__ }}",
    "{{ self._TemplateReference__context }}",
    "{{ config }}",
    "{{ request }}",
    "{{ ''.__class__.__mro__[1].__subclasses__()[0].__init__.__globals__ }}",
]


class TestJinja2SandboxEscapes:
    """The escapes above, asserted against the operator-enabled path."""

    @pytest.mark.parametrize('expression', JINJA2_ESCAPES)
    def test_escape_yields_no_choices(self, expression):
        with jinja2_enabled():
            assert _resolve_jinja2({'template': expression}) == []

    @pytest.mark.parametrize('expression', JINJA2_ESCAPES)
    def test_escape_never_reaches_the_module_table(self, expression):
        # Wrapping the expression in a JSON list matters: rendered bare, an
        # escape returns a Python repr that fails json.loads, so the empty
        # result would prove nothing. Wrapped, a successful escape parses
        # cleanly and comes back as a populated list. Against the pre-fix
        # renderer this exact shape returned ['x', 'posix'] for the cycler
        # payload, and the PATH environment variable for its os.environ variant.
        with jinja2_enabled():
            result = _resolve_jinja2({'template': '["x", "' + expression + '"]'})
        assert result == []

    def test_globals_are_gone(self):
        # range/dict/lipsum/cycler/namespace/joiner are removed outright, so the
        # escape above has nothing to start from even before the sandbox runs.
        with jinja2_enabled():
            for name in ('range', 'dict', 'lipsum', 'cycler', 'namespace', 'joiner'):
                assert _resolve_jinja2({'template': f'{{{{ {name} }}}}'}) == []

    def test_disallowed_filter_is_gone(self):
        with jinja2_enabled():
            assert _resolve_jinja2({'template': "{{ ['a'] | pprint }}"}) == []


class TestCacheScope:
    """
    The key has to carry the scope the answer was resolved in, or one tenant is
    served another's host names.
    """

    CONFIG = {'enabled': True, 'source_type': 'db_query', 'model': 'hosts', 'cache_ttl': 60}

    def test_same_question_different_inventory_gets_a_different_key(self):
        a = dynamic_survey._cache_key('v', self.CONFIG, fake_template(pk=1, inventory_id=10))
        b = dynamic_survey._cache_key('v', self.CONFIG, fake_template(pk=1, inventory_id=20))
        assert a and b and a != b

    def test_same_question_different_organization_gets_a_different_key(self):
        a = dynamic_survey._cache_key('v', self.CONFIG, fake_template(pk=1, organization_id=1))
        b = dynamic_survey._cache_key('v', self.CONFIG, fake_template(pk=1, organization_id=2))
        assert a and b and a != b

    def test_same_question_different_template_gets_a_different_key(self):
        a = dynamic_survey._cache_key('v', self.CONFIG, fake_template(pk=1))
        b = dynamic_survey._cache_key('v', self.CONFIG, fake_template(pk=2))
        assert a and b and a != b

    def test_identical_scope_reuses_the_key(self):
        a = dynamic_survey._cache_key('v', self.CONFIG, fake_template())
        b = dynamic_survey._cache_key('v', self.CONFIG, fake_template())
        assert a == b

    def test_no_template_means_no_key(self):
        assert dynamic_survey._cache_key('v', self.CONFIG, None) is None

    @patch('forail.main.services.dynamic_survey.cache')
    @patch('forail.main.services.dynamic_survey._resolve_db_query')
    def test_unscoped_resolution_is_not_cached(self, mock_resolve, mock_cache):
        # Better to resolve every time than to write an entry every tenant reads.
        mock_cache.get.return_value = None
        mock_resolve.return_value = ['h1']
        q = {'variable': 'v', 'dynamic_choices': dict(self.CONFIG)}
        assert resolve_dynamic_choices(q) == ['h1']
        mock_cache.set.assert_not_called()


# ===== _resolve_db_query =====

class TestDbQuery:

    def test_invalid_model(self):
        assert _resolve_db_query({'model': 'bad_model', 'field': 'name'}) == []

    def test_invalid_field(self):
        assert _resolve_db_query({'model': 'hosts', 'field': 'password'}) == []

    @patch('forail.main.services.dynamic_survey.apps')
    def test_valid_query(self, mock_apps):
        mock_qs = MagicMock()
        mock_qs.filter.return_value.values_list.return_value.distinct.return_value.order_by.return_value.__getitem__ = MagicMock(
            return_value=['h1', 'h2']
        )
        mock_model = MagicMock()
        mock_model.objects = mock_qs
        mock_apps.get_model.return_value = mock_model

        result = _resolve_db_query({'model': 'hosts', 'field': 'name', 'filter': {'inventory__id': 1}})
        assert result == ['h1', 'h2']

    @patch('forail.main.services.dynamic_survey.apps')
    def test_auto_inventory_filter(self, mock_apps):
        mock_qs = MagicMock()
        mock_qs.filter.return_value.values_list.return_value.distinct.return_value.order_by.return_value.__getitem__ = MagicMock(
            return_value=['h1']
        )
        mock_model = MagicMock()
        mock_model.objects = mock_qs
        mock_apps.get_model.return_value = mock_model

        template = MagicMock()
        template.inventory_id = 42

        result = _resolve_db_query({'model': 'hosts', 'field': 'name'}, template=template)
        # Should have added inventory__id filter
        mock_qs.filter.assert_called_once()
        call_kwargs = mock_qs.filter.call_args[1]
        assert call_kwargs.get('inventory__id') == 42


# ===== resolve_dynamic_choices (top-level) =====

class TestResolveDynamicChoices:

    @patch('forail.main.services.dynamic_survey.cache')
    def test_disabled_returns_none(self, mock_cache):
        q = {'variable': 'v', 'dynamic_choices': {'enabled': False}}
        assert resolve_dynamic_choices(q) is None

    @patch('forail.main.services.dynamic_survey.cache')
    def test_no_dc_returns_none(self, mock_cache):
        assert resolve_dynamic_choices({'variable': 'v'}) is None

    @patch('forail.main.services.dynamic_survey.cache')
    @patch('forail.main.services.dynamic_survey._resolve_db_query')
    def test_cache_hit(self, mock_resolve, mock_cache):
        mock_cache.get.return_value = ['c1', 'c2']
        q = {'variable': 'v', 'dynamic_choices': {'enabled': True, 'source_type': 'db_query', 'model': 'hosts', 'cache_ttl': 60}}
        result = resolve_dynamic_choices(q, template=fake_template())
        assert result == ['c1', 'c2']
        mock_resolve.assert_not_called()

    @patch('forail.main.services.dynamic_survey.cache')
    @patch('forail.main.services.dynamic_survey._resolve_db_query')
    def test_cache_miss(self, mock_resolve, mock_cache):
        mock_cache.get.return_value = None
        mock_resolve.return_value = ['h1', 'h2']
        q = {'variable': 'v', 'dynamic_choices': {'enabled': True, 'source_type': 'db_query', 'model': 'hosts', 'cache_ttl': 120}}
        result = resolve_dynamic_choices(q, template=fake_template())
        assert result == ['h1', 'h2']
        mock_cache.set.assert_called_once()
        # Verify TTL is passed
        assert mock_cache.set.call_args[1]['timeout'] == 120

    @patch('forail.main.services.dynamic_survey.cache')
    @patch('forail.main.services.dynamic_survey._resolve_api_endpoint')
    def test_api_source(self, mock_resolve, mock_cache):
        mock_cache.get.return_value = None
        mock_resolve.return_value = ['a1', 'a2']
        q = {'variable': 'v', 'dynamic_choices': {'enabled': True, 'source_type': 'api_endpoint', 'url': 'http://x', 'cache_ttl': 30}}
        result = resolve_dynamic_choices(q)
        assert result == ['a1', 'a2']

    @patch('forail.main.services.dynamic_survey.cache')
    @patch('forail.main.services.dynamic_survey._resolve_jinja2')
    def test_jinja2_source(self, mock_resolve, mock_cache):
        mock_cache.get.return_value = None
        mock_resolve.return_value = ['j1', 'j2']
        q = {'variable': 'v', 'dynamic_choices': {'enabled': True, 'source_type': 'jinja2', 'template': '{{ x }}', 'cache_ttl': 10}}
        with jinja2_enabled():
            result = resolve_dynamic_choices(q)
        assert result == ['j1', 'j2']

    @patch('forail.main.services.dynamic_survey.cache')
    def test_unknown_source_returns_empty(self, mock_cache):
        mock_cache.get.return_value = None
        q = {'variable': 'v', 'dynamic_choices': {'enabled': True, 'source_type': 'unknown', 'cache_ttl': 0}}
        result = resolve_dynamic_choices(q)
        assert result == []

    @patch('forail.main.services.dynamic_survey.cache')
    @patch('forail.main.services.dynamic_survey._resolve_db_query')
    def test_results_are_stringified(self, mock_resolve, mock_cache):
        mock_cache.get.return_value = None
        mock_resolve.return_value = [1, 2.5, True]
        q = {'variable': 'v', 'dynamic_choices': {'enabled': True, 'source_type': 'db_query', 'model': 'hosts', 'cache_ttl': 60}}
        result = resolve_dynamic_choices(q)
        assert result == ['1', '2.5', 'True']


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
