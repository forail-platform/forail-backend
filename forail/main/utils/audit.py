"""
Utility functions for logging audit events.
Called from signal handlers, task runners, and views.
"""
import logging

logger = logging.getLogger('forail.main.audit')


def log_credential_access(credential, job=None, actor=None, action='credential_used'):
    """
    Log credential access as an audit event.
    Called when a credential is used during job execution.
    """
    from forail.main.models.audit import AuditEvent

    detail = {}
    description_parts = [f'Credential "{credential.name}" (id={credential.id})']

    if job:
        detail['job_id'] = job.id
        detail['job_type'] = job.__class__.__name__
        description_parts.append(f'used for {job.__class__.__name__} #{job.id}')

    if hasattr(credential, 'credential_type') and credential.credential_type:
        detail['credential_type'] = credential.credential_type.name
        detail['credential_type_kind'] = credential.credential_type.kind

    organization = getattr(credential, 'organization', None)

    try:
        AuditEvent.log(
            category='credential_access',
            action=action,
            actor=actor,
            description=' '.join(description_parts),
            resource_type='credential',
            resource_id=credential.id,
            resource_name=credential.name,
            detail=detail,
            organization=organization,
        )
    except Exception:
        logger.exception('Failed to log credential access audit event')


def log_auth_event(action, actor=None, severity='info', description='', detail=None):
    """
    Log an authentication event (login, logout, login_failed, token_created, etc.)
    """
    from forail.main.models.audit import AuditEvent

    try:
        AuditEvent.log(
            category='auth',
            action=action,
            severity=severity,
            actor=actor,
            description=description,
            detail=detail or {},
        )
    except Exception:
        logger.exception('Failed to log auth audit event')


def log_permission_change(action, actor=None, resource_type='', resource_id=None,
                          resource_name='', description='', detail=None, organization=None):
    """
    Log a permission/RBAC change event.
    """
    from forail.main.models.audit import AuditEvent

    try:
        AuditEvent.log(
            category='permission_change',
            action=action,
            actor=actor,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_name=resource_name,
            description=description,
            detail=detail or {},
            organization=organization,
        )
    except Exception:
        logger.exception('Failed to log permission change audit event')
