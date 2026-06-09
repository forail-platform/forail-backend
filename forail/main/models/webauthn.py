"""
WebAuthn / FIDO2 models for Forail.

Stores per-user FIDO2 credentials and short-lived registration / authentication
challenges. Used by:
  * passwordless first-factor login (username + WebAuthn assertion)
  * second-factor MFA after primary auth (when org enforces it)
"""

import logging

from django.db import models
from django.utils.translation import gettext_lazy as _

from forail.api.versioning import reverse
from forail.main.models.base import CreatedModifiedModel

logger = logging.getLogger('forail.main.models.webauthn')

__all__ = [
    'WebAuthnCredential',
    'WebAuthnRegistrationChallenge',
    'WebAuthnAuthenticationChallenge',
]


class WebAuthnCredential(CreatedModifiedModel):
    """A registered FIDO2 credential bound to a single user."""

    class Meta:
        app_label = 'main'
        ordering = ('-created',)
        indexes = [
            models.Index(fields=['user', '-created']),
        ]

    user = models.ForeignKey(
        'auth.User',
        on_delete=models.CASCADE,
        related_name='webauthn_credentials',
    )

    credential_id = models.BinaryField(
        unique=True,
        help_text=_('Raw credential ID returned by the authenticator.'),
    )
    public_key = models.BinaryField(
        help_text=_('COSE-encoded public key for assertion verification.'),
    )
    sign_count = models.PositiveIntegerField(
        default=0,
        help_text=_('Authenticator signature counter — must monotonically increase.'),
    )

    transports = models.JSONField(
        default=list,
        blank=True,
        help_text=_('List of advertised transports (usb, nfc, ble, internal, hybrid).'),
    )
    aaguid = models.CharField(
        max_length=36,
        blank=True,
        default='',
        help_text=_('Authenticator AAGUID (UUID).'),
    )

    label = models.CharField(
        max_length=128,
        blank=True,
        default='',
        help_text=_('User-facing nickname for this credential.'),
    )

    last_used_at = models.DateTimeField(null=True, blank=True)

    backup_eligible = models.BooleanField(default=False)
    backup_state = models.BooleanField(default=False)

    def get_absolute_url(self, request=None):
        return reverse('api:webauthn_credential_detail', kwargs={'pk': self.pk}, request=request)

    def __str__(self):
        return f'WebAuthnCredential #{self.pk} ({self.label or "unnamed"}) for {self.user_id}'


class _ChallengeBase(models.Model):
    """Common fields for short-lived WebAuthn challenges."""

    class Meta:
        abstract = True
        app_label = 'main'

    challenge = models.BinaryField(
        unique=True,
        help_text=_('Raw random bytes sent to the authenticator.'),
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    expires_at = models.DateTimeField(db_index=True)


class WebAuthnRegistrationChallenge(_ChallengeBase):
    """Challenge issued during the begin-register step, consumed at complete-register."""

    class Meta:
        app_label = 'main'
        ordering = ('-created_at',)

    user = models.ForeignKey(
        'auth.User',
        on_delete=models.CASCADE,
        related_name='webauthn_registration_challenges',
    )

    def __str__(self):
        return f'RegChallenge #{self.pk} user={self.user_id}'


class WebAuthnAuthenticationChallenge(_ChallengeBase):
    """Challenge issued during begin-authenticate; user is optional for passwordless flows."""

    class Meta:
        app_label = 'main'
        ordering = ('-created_at',)

    user = models.ForeignKey(
        'auth.User',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='webauthn_auth_challenges',
        help_text=_('Set when the user is known up-front (MFA), null for passwordless discovery.'),
    )

    def __str__(self):
        return f'AuthChallenge #{self.pk} user={self.user_id}'


# ----------------------------------------------------------------------
# MFA policy resolver — pure function used by the post-login middleware
# and tested standalone.
# ----------------------------------------------------------------------

WEBAUTHN_REQUIRED_NONE = 'none'
WEBAUTHN_REQUIRED_ADMINS = 'admins'
WEBAUTHN_REQUIRED_ALL = 'all'

WEBAUTHN_REQUIRED_CHOICES = [
    (WEBAUTHN_REQUIRED_NONE, _('Not required')),
    (WEBAUTHN_REQUIRED_ADMINS, _('Required for admins only')),
    (WEBAUTHN_REQUIRED_ALL, _('Required for all members')),
]


def is_webauthn_required(setting, is_admin):
    """Pure resolver: given a setting value and whether the user is an admin,
    return True if WebAuthn assertion is required to complete login."""
    if setting == WEBAUTHN_REQUIRED_ALL:
        return True
    if setting == WEBAUTHN_REQUIRED_ADMINS and is_admin:
        return True
    return False


def is_replay(stored_count, presented_count):
    """Authenticator replay detection — the new counter must strictly exceed
    the stored one (or both must be zero, which some authenticators do)."""
    if stored_count == 0 and presented_count == 0:
        return False
    return presented_count <= stored_count
