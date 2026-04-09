"""Standalone unit tests for the observability pure helpers.

These tests deliberately do NOT import ``opentelemetry`` or Django — they
load ``forge/main/observability/helpers.py`` directly via importlib so they
can run in any minimal environment.
"""

import os
import sys
import unittest
import importlib.util
from datetime import datetime, timedelta, timezone


def _load(mod_name, rel_path):
    path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', rel_path))
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


helpers = _load('obs_helpers', 'forge/main/observability/helpers.py')

parse_resource_attributes = helpers.parse_resource_attributes
parse_endpoint = helpers.parse_endpoint
is_otlp_grpc = helpers.is_otlp_grpc
is_otlp_http = helpers.is_otlp_http
validate_sampler_arg = helpers.validate_sampler_arg
aggregate_health = helpers.aggregate_health
should_recheck_health = helpers.should_recheck_health


class TestParseResourceAttributes(unittest.TestCase):
    def test_empty_string(self):
        self.assertEqual(parse_resource_attributes(''), {})

    def test_single_pair(self):
        self.assertEqual(parse_resource_attributes('a=1'), {'a': '1'})

    def test_multiple_pairs(self):
        self.assertEqual(
            parse_resource_attributes('a=1,b=2,c=3'),
            {'a': '1', 'b': '2', 'c': '3'},
        )

    def test_whitespace_stripped(self):
        self.assertEqual(
            parse_resource_attributes('a=1, b = 2 '),
            {'a': '1', 'b': '2'},
        )

    def test_malformed_skipped(self):
        self.assertEqual(parse_resource_attributes('garbage,a=1'), {'a': '1'})


class TestParseEndpoint(unittest.TestCase):
    def test_http_scheme_with_port(self):
        self.assertEqual(parse_endpoint('http://x:4317'), ('x', 4317, 'http'))

    def test_https_scheme_with_port(self):
        self.assertEqual(
            parse_endpoint('https://otel.example:4318'),
            ('otel.example', 4318, 'https'),
        )

    def test_bare_host_port_defaults_http(self):
        self.assertEqual(parse_endpoint('localhost:4317'), ('localhost', 4317, 'http'))


class TestIsOtlp(unittest.TestCase):
    def test_is_grpc_true(self):
        self.assertTrue(is_otlp_grpc('http://x:4317'))

    def test_is_grpc_false_for_4318(self):
        self.assertFalse(is_otlp_grpc('http://x:4318'))

    def test_is_http_by_v1_path(self):
        self.assertTrue(is_otlp_http('http://x:4318/v1/traces'))

    def test_is_http_by_port(self):
        self.assertTrue(is_otlp_http('http://x:4318'))


class TestValidateSamplerArg(unittest.TestCase):
    def test_valid_midrange(self):
        self.assertEqual(validate_sampler_arg('0.5'), 0.5)

    def test_clamped_high(self):
        self.assertEqual(validate_sampler_arg('1.5'), 1.0)

    def test_clamped_low(self):
        self.assertEqual(validate_sampler_arg('-0.1'), 0.0)

    def test_invalid_defaults_to_0_1(self):
        self.assertEqual(validate_sampler_arg('not a number'), 0.1)


class TestAggregateHealth(unittest.TestCase):
    def test_none_is_unhealthy(self):
        self.assertFalse(aggregate_health(None))

    def test_recent_is_healthy(self):
        now = datetime(2026, 4, 9, 12, 0, 0, tzinfo=timezone.utc)
        past = (now - timedelta(seconds=10)).isoformat()
        self.assertTrue(aggregate_health(past, ttl_seconds=30, now=now))

    def test_old_is_unhealthy(self):
        now = datetime(2026, 4, 9, 12, 0, 0, tzinfo=timezone.utc)
        past = (now - timedelta(seconds=60)).isoformat()
        self.assertFalse(aggregate_health(past, ttl_seconds=30, now=now))

    def test_should_recheck_is_inverse(self):
        now = datetime(2026, 4, 9, 12, 0, 0, tzinfo=timezone.utc)
        fresh = (now - timedelta(seconds=5)).isoformat()
        stale = (now - timedelta(seconds=120)).isoformat()
        self.assertFalse(should_recheck_health(fresh, ttl_seconds=30, now=now))
        self.assertTrue(should_recheck_health(stale, ttl_seconds=30, now=now))
        self.assertTrue(should_recheck_health(None))


if __name__ == '__main__':
    unittest.main()
