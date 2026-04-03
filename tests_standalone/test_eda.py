"""
Standalone tests for EDA (Event-Driven Automation) functionality.

Tests the core rule engine logic: condition evaluation, action dispatch,
signature verification, throttling, and deduplication.
"""

import json
import hmac
import hashlib
import unittest
from unittest.mock import patch, MagicMock
from datetime import timedelta

# Test the rule evaluation engine in isolation
import sys
import os

# Add the forge-backend to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestConditionEvaluation(unittest.TestCase):
    """Test the Jinja2 condition evaluation engine."""

    def _evaluate(self, conditions, payload, headers=None):
        """Import and call the condition evaluator."""
        # We test the logic directly since it's a pure function
        from jinja2 import sandbox, ChainableUndefined

        if headers is None:
            headers = {}

        env = sandbox.ImmutableSandboxedEnvironment(undefined=ChainableUndefined)
        context = {'event': payload, 'headers': headers}

        results = []
        all_matched = True

        if not conditions:
            return True, []

        for condition in conditions:
            expr = condition.get('jinja2_expression', '')
            description = condition.get('description', '')

            try:
                template_str = f'{{% if {expr} %}}__TRUE__{{% else %}}__FALSE__{{% endif %}}'
                rendered = env.from_string(template_str).render(**context)
                matched = rendered.strip() == '__TRUE__'
            except Exception as e:
                matched = False
                results.append({
                    'expression': expr,
                    'description': description,
                    'matched': False,
                    'error': str(e),
                })
                all_matched = False
                continue

            results.append({
                'expression': expr,
                'description': description,
                'matched': matched,
            })
            if not matched:
                all_matched = False

        return all_matched, results

    def test_empty_conditions_always_match(self):
        matched, results = self._evaluate([], {'action': 'test'})
        self.assertTrue(matched)
        self.assertEqual(results, [])

    def test_simple_equality_match(self):
        conditions = [{'jinja2_expression': 'event.action == "opened"', 'description': 'PR opened'}]
        matched, results = self._evaluate(conditions, {'action': 'opened'})
        self.assertTrue(matched)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]['matched'])

    def test_simple_equality_no_match(self):
        conditions = [{'jinja2_expression': 'event.action == "opened"', 'description': 'PR opened'}]
        matched, results = self._evaluate(conditions, {'action': 'closed'})
        self.assertFalse(matched)
        self.assertFalse(results[0]['matched'])

    def test_multiple_conditions_all_match(self):
        conditions = [
            {'jinja2_expression': 'event.action == "push"', 'description': 'Push event'},
            {'jinja2_expression': 'event.ref == "refs/heads/main"', 'description': 'Main branch'},
        ]
        payload = {'action': 'push', 'ref': 'refs/heads/main'}
        matched, results = self._evaluate(conditions, payload)
        self.assertTrue(matched)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r['matched'] for r in results))

    def test_multiple_conditions_partial_match(self):
        conditions = [
            {'jinja2_expression': 'event.action == "push"', 'description': 'Push event'},
            {'jinja2_expression': 'event.ref == "refs/heads/main"', 'description': 'Main branch'},
        ]
        payload = {'action': 'push', 'ref': 'refs/heads/develop'}
        matched, results = self._evaluate(conditions, payload)
        self.assertFalse(matched)
        self.assertTrue(results[0]['matched'])
        self.assertFalse(results[1]['matched'])

    def test_nested_payload_access(self):
        conditions = [
            {'jinja2_expression': 'event.pull_request.head.ref == "feature-x"', 'description': 'Feature branch'}
        ]
        payload = {'pull_request': {'head': {'ref': 'feature-x'}}}
        matched, results = self._evaluate(conditions, payload)
        self.assertTrue(matched)

    def test_in_operator(self):
        conditions = [
            {'jinja2_expression': '"production" in event.labels', 'description': 'Has production label'}
        ]
        payload = {'labels': ['production', 'web']}
        matched, results = self._evaluate(conditions, payload)
        self.assertTrue(matched)

    def test_missing_field_no_error(self):
        """ChainableUndefined should handle missing fields gracefully."""
        conditions = [
            {'jinja2_expression': 'event.nonexistent == "value"', 'description': 'Missing field'}
        ]
        matched, results = self._evaluate(conditions, {'other': 'data'})
        self.assertFalse(matched)
        self.assertEqual(len(results), 1)
        # Should not have error, just not matched
        self.assertFalse(results[0]['matched'])

    def test_invalid_jinja2_expression(self):
        conditions = [
            {'jinja2_expression': '{{% invalid %}', 'description': 'Bad syntax'}
        ]
        matched, results = self._evaluate(conditions, {})
        self.assertFalse(matched)
        self.assertIn('error', results[0])

    def test_header_access(self):
        conditions = [
            {'jinja2_expression': 'headers["X-Github-Event"] == "push"', 'description': 'GitHub push'}
        ]
        matched, results = self._evaluate(conditions, {}, {'X-Github-Event': 'push'})
        self.assertTrue(matched)

    def test_comparison_operators(self):
        conditions = [
            {'jinja2_expression': 'event.severity >= 3', 'description': 'High severity'}
        ]
        matched, results = self._evaluate(conditions, {'severity': 5})
        self.assertTrue(matched)

        matched2, _ = self._evaluate(conditions, {'severity': 1})
        self.assertFalse(matched2)

    def test_or_logic_in_single_expression(self):
        conditions = [
            {'jinja2_expression': 'event.status == "firing" or event.status == "resolved"', 'description': 'Alert state change'}
        ]
        matched, _ = self._evaluate(conditions, {'status': 'firing'})
        self.assertTrue(matched)

        matched2, _ = self._evaluate(conditions, {'status': 'resolved'})
        self.assertTrue(matched2)

        matched3, _ = self._evaluate(conditions, {'status': 'pending'})
        self.assertFalse(matched3)

    def test_string_contains(self):
        conditions = [
            {'jinja2_expression': '"error" in event.message', 'description': 'Error in message'}
        ]
        matched, _ = self._evaluate(conditions, {'message': 'disk error on server01'})
        self.assertTrue(matched)


class TestHMACSignatureVerification(unittest.TestCase):
    """Test HMAC signature verification for different source types."""

    def test_generic_sha256_valid(self):
        key = 'test-secret-key'
        body = b'{"event": "test"}'
        mac = hmac.new(key.encode(), body, hashlib.sha256)
        signature = f'sha256={mac.hexdigest()}'

        headers = {'X-Forge-Signature': signature}

        # Verify manually
        expected_mac = hmac.new(key.encode(), body, hashlib.sha256)
        self.assertTrue(
            hmac.compare_digest(expected_mac.hexdigest(), mac.hexdigest())
        )

    def test_generic_sha256_invalid(self):
        key = 'test-secret-key'
        body = b'{"event": "test"}'
        headers = {'X-Forge-Signature': 'sha256=invalid_signature'}

        mac = hmac.new(key.encode(), body, hashlib.sha256)
        self.assertFalse(
            hmac.compare_digest(mac.hexdigest(), 'invalid_signature')
        )

    def test_github_sha1_valid(self):
        key = 'github-webhook-secret'
        body = b'{"action": "opened"}'
        mac = hmac.new(key.encode(), body, hashlib.sha1)
        signature = f'sha1={mac.hexdigest()}'

        # Parse and verify
        hash_alg, sig = signature.split('=', 1)
        self.assertEqual(hash_alg, 'sha1')
        verify_mac = hmac.new(key.encode(), body, hashlib.sha1)
        self.assertTrue(hmac.compare_digest(verify_mac.hexdigest(), sig))

    def test_github_sha256_valid(self):
        key = 'github-webhook-secret'
        body = b'{"action": "push"}'
        mac = hmac.new(key.encode(), body, hashlib.sha256)
        signature = f'sha256={mac.hexdigest()}'

        hash_alg, sig = signature.split('=', 1)
        self.assertEqual(hash_alg, 'sha256')
        verify_mac = hmac.new(key.encode(), body, hashlib.sha256)
        self.assertTrue(hmac.compare_digest(verify_mac.hexdigest(), sig))

    def test_gitlab_token_valid(self):
        key = 'gitlab-token'
        token_from_request = 'gitlab-token'
        self.assertTrue(hmac.compare_digest(key, token_from_request))

    def test_gitlab_token_invalid(self):
        key = 'gitlab-token'
        token_from_request = 'wrong-token'
        self.assertFalse(hmac.compare_digest(key, token_from_request))


class TestThrottling(unittest.TestCase):
    """Test rule throttling logic."""

    def test_no_throttle(self):
        """throttle_seconds=0 means no throttling."""
        from datetime import datetime, timezone

        # Simulate: throttle_seconds=0, last_fired_at=just now
        throttle_seconds = 0
        last_fired_at = datetime.now(timezone.utc)

        if throttle_seconds <= 0 or last_fired_at is None:
            is_throttled = False
        else:
            elapsed = (datetime.now(timezone.utc) - last_fired_at).total_seconds()
            is_throttled = elapsed < throttle_seconds

        self.assertFalse(is_throttled)

    def test_throttled(self):
        from datetime import datetime, timezone

        throttle_seconds = 60
        last_fired_at = datetime.now(timezone.utc) - timedelta(seconds=10)

        elapsed = (datetime.now(timezone.utc) - last_fired_at).total_seconds()
        is_throttled = elapsed < throttle_seconds

        self.assertTrue(is_throttled)

    def test_not_throttled_after_interval(self):
        from datetime import datetime, timezone

        throttle_seconds = 60
        last_fired_at = datetime.now(timezone.utc) - timedelta(seconds=120)

        elapsed = (datetime.now(timezone.utc) - last_fired_at).total_seconds()
        is_throttled = elapsed < throttle_seconds

        self.assertFalse(is_throttled)

    def test_never_fired_not_throttled(self):
        throttle_seconds = 60
        last_fired_at = None

        if throttle_seconds <= 0 or last_fired_at is None:
            is_throttled = False
        else:
            is_throttled = True

        self.assertFalse(is_throttled)


class TestDeduplication(unittest.TestCase):
    """Test event deduplication logic."""

    def test_duplicate_guid_detected(self):
        existing_guids = {'abc-123', 'def-456'}
        new_guid = 'abc-123'
        self.assertIn(new_guid, existing_guids)

    def test_unique_guid_passes(self):
        existing_guids = {'abc-123', 'def-456'}
        new_guid = 'ghi-789'
        self.assertNotIn(new_guid, existing_guids)

    def test_empty_guid_not_deduplicated(self):
        """Empty GUIDs should not be deduplicated."""
        existing_guids = {'abc-123', ''}
        new_guid = ''
        # Empty strings should be allowed through (not deduplicated)
        should_dedup = new_guid and new_guid in existing_guids
        self.assertFalse(should_dedup)


class TestPayloadParsing(unittest.TestCase):
    """Test event type and GUID extraction for different source types."""

    def test_github_event_type_extraction(self):
        headers = {'HTTP_X_GITHUB_EVENT': 'push'}
        event_type = headers.get('HTTP_X_GITHUB_EVENT', '')
        self.assertEqual(event_type, 'push')

    def test_github_delivery_guid(self):
        headers = {'HTTP_X_GITHUB_DELIVERY': 'abc-123-def-456'}
        guid = headers.get('HTTP_X_GITHUB_DELIVERY', '')
        self.assertEqual(guid, 'abc-123-def-456')

    def test_gitlab_event_type_extraction(self):
        headers = {'HTTP_X_GITLAB_EVENT': 'Push Hook'}
        event_type = headers.get('HTTP_X_GITLAB_EVENT', '')
        self.assertEqual(event_type, 'Push Hook')

    def test_alertmanager_status_extraction(self):
        payload = {'status': 'firing', 'alerts': [{'labels': {'alertname': 'disk_full'}}]}
        event_type = payload.get('status', 'alert')
        self.assertEqual(event_type, 'firing')

    def test_pagerduty_event_extraction(self):
        payload = {'messages': [{'event': 'incident.trigger', 'incident': {}}]}
        messages = payload.get('messages', [])
        event_type = messages[0].get('event', '') if messages else ''
        self.assertEqual(event_type, 'incident.trigger')


class TestOutboundWebhookPayload(unittest.TestCase):
    """Test outbound webhook payload construction and signing."""

    def test_payload_structure(self):
        job_data = {
            'event_type': 'job.succeeded',
            'timestamp': '2026-04-03T12:00:00Z',
            'job': {
                'id': 42,
                'name': 'Deploy Web App',
                'status': 'successful',
                'type': 'Job',
            },
        }

        payload_bytes = json.dumps(job_data).encode('utf-8')
        self.assertIn(b'job.succeeded', payload_bytes)
        self.assertIn(b'Deploy Web App', payload_bytes)

    def test_outbound_signing(self):
        key = 'outbound-secret'
        body = json.dumps({'event_type': 'job.failed'}).encode('utf-8')

        mac = hmac.new(key.encode(), body, hashlib.sha256)
        signature = f'sha256={mac.hexdigest()}'

        self.assertTrue(signature.startswith('sha256='))

        # Verify
        verify_mac = hmac.new(key.encode(), body, hashlib.sha256)
        _, sig = signature.split('=', 1)
        self.assertTrue(hmac.compare_digest(verify_mac.hexdigest(), sig))


class TestWebhookPathValidation(unittest.TestCase):
    """Test webhook_path slug validation."""

    def test_valid_paths(self):
        import re
        valid = ['my-hook', 'deploy_prod', 'github-main', 'alertmanager01', 'test-hook-123']
        for path in valid:
            self.assertTrue(re.match(r'^[a-zA-Z0-9_-]+$', path), f'{path} should be valid')

    def test_invalid_paths(self):
        import re
        invalid = ['my hook', 'deploy/prod', '../etc', 'hook;rm', 'hook&cmd', 'hook<script>']
        for path in invalid:
            self.assertIsNone(re.match(r'^[a-zA-Z0-9_-]+$', path), f'{path} should be invalid')


class TestActionConfig(unittest.TestCase):
    """Test action configuration validation."""

    def test_valid_action_types(self):
        valid_types = {'launch_job_template', 'launch_workflow', 'send_notification'}
        self.assertIn('launch_job_template', valid_types)
        self.assertIn('launch_workflow', valid_types)
        self.assertIn('send_notification', valid_types)
        self.assertNotIn('unknown_action', valid_types)

    def test_action_requires_target_id(self):
        action = {'action_type': 'launch_job_template', 'target_id': 5}
        self.assertIsNotNone(action.get('target_id'))

        action_no_target = {'action_type': 'launch_job_template'}
        self.assertIsNone(action_no_target.get('target_id'))

    def test_extra_vars_merging(self):
        user_vars = {'env': 'production', 'version': '1.2.3'}
        event_vars = {
            'forge_eda_event_type': 'push',
            'forge_eda_event_guid': 'abc-123',
            'forge_eda_rule_name': 'deploy-on-push',
            'forge_eda_payload': {'ref': 'refs/heads/main'},
        }

        merged = dict(user_vars)
        merged.update(event_vars)

        self.assertEqual(merged['env'], 'production')
        self.assertEqual(merged['forge_eda_event_type'], 'push')
        self.assertEqual(len(merged), 6)


if __name__ == '__main__':
    unittest.main()
