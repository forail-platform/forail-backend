from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from forail.api.versioning import reverse

__all__ = ['AuditEvent']


class AuditEvent(models.Model):
    """
    Immutable audit event log. Append-only — entries cannot be updated or deleted
    through the ORM. Used for compliance-grade auditing of security-sensitive
    operations: credential access, authentication events, permission changes.
    """

    class Meta:
        app_label = 'main'
        ordering = ('-timestamp',)

    CATEGORY_CHOICES = [
        ('auth', _('Authentication')),
        ('credential_access', _('Credential Access')),
        ('permission_change', _('Permission Change')),
        ('resource_change', _('Resource Change')),
        ('system', _('System Event')),
    ]

    SEVERITY_CHOICES = [
        ('info', _('Info')),
        ('warning', _('Warning')),
        ('critical', _('Critical')),
    ]

    # When
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    # Who
    actor = models.ForeignKey(
        'auth.User',
        null=True,
        on_delete=models.SET_NULL,
        related_name='audit_events',
    )
    actor_username = models.CharField(
        max_length=150,
        blank=True,
        default='',
        help_text=_("Denormalized username, preserved after user deletion."),
    )
    actor_ip = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text=_("IP address of the actor."),
    )
    actor_user_agent = models.CharField(
        max_length=512,
        blank=True,
        default='',
    )
    actor_session_id = models.CharField(
        max_length=64,
        blank=True,
        default='',
    )

    # What
    category = models.CharField(
        max_length=32,
        choices=CATEGORY_CHOICES,
        db_index=True,
    )
    severity = models.CharField(
        max_length=16,
        choices=SEVERITY_CHOICES,
        default='info',
    )
    action = models.CharField(
        max_length=128,
        help_text=_("Action performed, e.g. 'login', 'credential_used', 'role_granted'."),
        db_index=True,
    )
    description = models.TextField(
        blank=True,
        default='',
        help_text=_("Human-readable description of the event."),
    )

    # On what
    resource_type = models.CharField(
        max_length=128,
        blank=True,
        default='',
        help_text=_("Type of resource affected, e.g. 'credential', 'job_template'."),
        db_index=True,
    )
    resource_id = models.IntegerField(
        null=True,
        blank=True,
        help_text=_("ID of the affected resource."),
    )
    resource_name = models.CharField(
        max_length=512,
        blank=True,
        default='',
        help_text=_("Name of the affected resource at the time of the event."),
    )

    # Where
    action_node = models.CharField(
        max_length=512,
        blank=True,
        default='',
        help_text=_("Cluster node where the event occurred."),
    )

    # Extra data
    detail = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Additional structured data for the event."),
    )

    # Organization scope for RBAC filtering
    organization = models.ForeignKey(
        'Organization',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='audit_events',
    )

    def __str__(self):
        return f'{self.category}:{self.action} by {self.actor_username} at {self.timestamp}'

    def get_absolute_url(self, request=None):
        return reverse('api:audit_event_detail', kwargs={'pk': self.pk}, request=request)

    def save(self, *args, **kwargs):
        # Immutability: only allow inserts, not updates
        if self.pk:
            raise ValueError("AuditEvent entries are immutable and cannot be updated.")

        # Denormalize actor username
        if self.actor and not self.actor_username:
            self.actor_username = self.actor.username

        # Populate from request context if not set
        from forail.main.middleware import get_request_context
        ctx = get_request_context()
        if not self.actor_ip and ctx['actor_ip']:
            self.actor_ip = ctx['actor_ip']
        if not self.actor_user_agent and ctx['actor_user_agent']:
            self.actor_user_agent = ctx['actor_user_agent']
        if not self.actor_session_id and ctx['actor_session_id']:
            self.actor_session_id = ctx['actor_session_id']

        # Populate action node
        hostname_char_limit = self._meta.get_field('action_node').max_length
        self.action_node = settings.CLUSTER_HOST_ID[:hostname_char_limit]

        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("AuditEvent entries are immutable and cannot be deleted.")

    @classmethod
    def log(cls, category, action, severity='info', actor=None, description='',
            resource_type='', resource_id=None, resource_name='', detail=None,
            organization=None):
        """
        Convenience method for creating audit events.

        Usage:
            AuditEvent.log(
                category='credential_access',
                action='credential_used',
                actor=user,
                resource_type='credential',
                resource_id=cred.id,
                resource_name=cred.name,
                description=f'Credential "{cred.name}" used for job #{job.id}',
                detail={'job_id': job.id, 'hosts': ['web-01', 'web-02']},
            )
        """
        from crum import get_current_user
        if actor is None:
            actor = get_current_user()

        event = cls(
            category=category,
            action=action,
            severity=severity,
            actor=actor,
            description=description,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_name=resource_name,
            detail=detail or {},
            organization=organization,
        )
        event.save()
        return event
