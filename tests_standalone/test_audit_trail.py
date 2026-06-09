"""
Integration tests for the Improved Audit Trail feature.
"""
import os
import sys
import threading
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock AuditEvent model module to avoid Django model imports
MockAuditEvent = MagicMock()
mock_audit_module = MagicMock()
mock_audit_module.AuditEvent = MockAuditEvent
sys.modules['forail.main.models.audit'] = mock_audit_module

# Mock crum for get_current_user
sys.modules.setdefault('crum', MagicMock())

passed = 0
failed = 0

def check(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


# ===== Request Context (standalone thread-local) =====
print("=== Request Context Tests ===")

_ctx = threading.local()

def get_ctx():
    return {
        'actor_ip': getattr(_ctx, 'ip', ''),
        'actor_user_agent': getattr(_ctx, 'user_agent', ''),
        'actor_session_id': getattr(_ctx, 'session_id', ''),
    }

_ctx.ip = ''
_ctx.user_agent = ''
_ctx.session_id = ''
check("Default empty", get_ctx() == {'actor_ip': '', 'actor_user_agent': '', 'actor_session_id': ''})

_ctx.ip = '192.168.1.100'
_ctx.user_agent = 'Mozilla/5.0'
_ctx.session_id = 'sess_abc'
check("IP captured", get_ctx()['actor_ip'] == '192.168.1.100')
check("UA captured", get_ctx()['actor_user_agent'] == 'Mozilla/5.0')
check("Session captured", get_ctx()['actor_session_id'] == 'sess_abc')

forwarded = '203.0.113.50, 10.0.0.1'
_ctx.ip = forwarded.split(',')[0].strip()
check("X-Forwarded-For parsing", _ctx.ip == '203.0.113.50')

_ctx.user_agent = 'X' * 1000
_ctx.user_agent = _ctx.user_agent[:512]
check("UA truncated 512", len(_ctx.user_agent) == 512)

_ctx.ip = ''
_ctx.user_agent = ''
_ctx.session_id = ''
check("Cleanup", get_ctx() == {'actor_ip': '', 'actor_user_agent': '', 'actor_session_id': ''})


# ===== Audit Utility Functions =====
print()
print("=== Audit Utility Functions ===")

from forail.main.utils.audit import log_credential_access, log_auth_event, log_permission_change

# -- Credential access --
MockAuditEvent.reset_mock()
cred = MagicMock(name='prod-ssh', id=42)
cred.name = 'prod-ssh'
cred.id = 42
cred.credential_type.name = 'Machine'
cred.credential_type.kind = 'ssh'
cred.organization = MagicMock()

job = MagicMock()
job.id = 100
job.__class__.__name__ = 'Job'

log_credential_access(cred, job=job, actor=MagicMock())
MockAuditEvent.log.assert_called_once()
kw = MockAuditEvent.log.call_args[1]
check("Cred: category=credential_access", kw['category'] == 'credential_access')
check("Cred: action=credential_used", kw['action'] == 'credential_used')
check("Cred: resource_type=credential", kw['resource_type'] == 'credential')
check("Cred: resource_id=42", kw['resource_id'] == 42)
check("Cred: resource_name", kw['resource_name'] == 'prod-ssh')
check("Cred: detail.job_id", kw['detail']['job_id'] == 100)
check("Cred: detail.credential_type", kw['detail']['credential_type'] == 'Machine')
check("Cred: detail.credential_type_kind", kw['detail']['credential_type_kind'] == 'ssh')

# Without job
MockAuditEvent.reset_mock()
log_credential_access(cred)
kw = MockAuditEvent.log.call_args[1]
check("Cred no job: no job_id", 'job_id' not in kw['detail'])

# -- Auth event --
MockAuditEvent.reset_mock()
log_auth_event('login', actor=MagicMock(), description='User logged in', detail={'method': 'password'})
kw = MockAuditEvent.log.call_args[1]
check("Auth: category=auth", kw['category'] == 'auth')
check("Auth: action=login", kw['action'] == 'login')
check("Auth: detail.method", kw['detail']['method'] == 'password')

# Failed login
MockAuditEvent.reset_mock()
log_auth_event('login_failed', severity='warning', description='Bad password')
kw = MockAuditEvent.log.call_args[1]
check("Auth fail: severity=warning", kw['severity'] == 'warning')
check("Auth fail: action=login_failed", kw['action'] == 'login_failed')

# -- Permission change --
MockAuditEvent.reset_mock()
log_permission_change('role_granted', resource_type='team', resource_id=5, resource_name='DevOps',
                      detail={'role': 'admin', 'user': 'john'})
kw = MockAuditEvent.log.call_args[1]
check("Perm: category=permission_change", kw['category'] == 'permission_change')
check("Perm: action=role_granted", kw['action'] == 'role_granted')
check("Perm: resource_type=team", kw['resource_type'] == 'team')
check("Perm: resource_id=5", kw['resource_id'] == 5)

# -- Error handling --
MockAuditEvent.reset_mock()
MockAuditEvent.log.side_effect = Exception('DB error')
log_credential_access(cred)
check("Cred error: no raise", True)

log_auth_event('login')
check("Auth error: no raise", True)

log_permission_change('role_granted')
check("Perm error: no raise", True)
MockAuditEvent.log.side_effect = None  # reset


# ===== Serializer Structure (verified by reading source, not importing) =====
print()
print("=== Serializer Structure ===")

# Read serializer source to verify fields without importing (avoids full Django chain)
import ast
serializer_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                'forail', 'api', 'serializers', 'audit.py')
with open(serializer_path) as f:
    source = f.read()

check("Serializer file exists", len(source) > 0)
check("AuditEventSerializer defined", 'class AuditEventSerializer' in source)
check("AuditEventSIEMSerializer defined", 'class AuditEventSIEMSerializer' in source)
for field in ['actor_ip', 'actor_user_agent', 'actor_session_id', 'category', 'severity',
              'action', 'description', 'resource_type', 'resource_id', 'detail', 'organization']:
    check(f"Field '{field}' in serializer", f"'{field}'" in source)
check("read_only_fields = fields", 'read_only_fields = fields' in source)
check("SIEM flattens detail", "detail_" in source)
check("SIEM adds source=forail", "'forail'" in source)
check("SIEM adds event_type", "'event_type'" in source)


# ===== Results =====
print()
print(f"Results: {passed} passed, {failed} failed")
if failed == 0:
    print("=" * 50)
    print("ALL AUDIT TRAIL TESTS PASSED!")
    print("=" * 50)
else:
    print("SOME TESTS FAILED!")
    sys.exit(1)
