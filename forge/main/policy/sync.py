"""Push Rego modules to the OPA sidecar on save / delete."""

import logging

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.utils.timezone import now

logger = logging.getLogger('forge.main.policy.sync')


def _opa_url():
    from django.conf import settings
    return getattr(settings, 'OPA_SERVER_URL', '')


def _timeout_ms():
    from django.conf import settings
    return int(getattr(settings, 'OPA_EVALUATION_TIMEOUT_MS', 2000))


def push_policy(policy):
    """Best-effort upload — never raises. Updates policy.last_sync_status."""
    from forge.main.policy.opa_client import upload_policy, OPAUnavailable
    if not policy.enabled or not policy.rego_module:
        return
    try:
        upload_policy(_opa_url(), policy.id, policy.rego_module, _timeout_ms())
        policy.__class__.objects.filter(pk=policy.pk).update(
            last_sync_status='ok', last_evaluated_at=now(),
        )
    except OPAUnavailable as e:
        logger.warning('Failed to push policy %s to OPA: %s', policy.id, e)
        policy.__class__.objects.filter(pk=policy.pk).update(last_sync_status='failed')


def remove_policy(policy_id):
    from forge.main.policy.opa_client import delete_policy, OPAUnavailable
    try:
        delete_policy(_opa_url(), policy_id, _timeout_ms())
    except OPAUnavailable as e:
        logger.warning('Failed to remove policy %s from OPA: %s', policy_id, e)


@receiver(post_save, sender=None)
def _on_policy_save(sender, instance, **kwargs):  # pragma: no cover - signal
    if sender is None:
        return
    try:
        from forge.main.models.policy import Policy
    except Exception:
        return
    if not isinstance(instance, Policy):
        return
    push_policy(instance)


@receiver(post_delete, sender=None)
def _on_policy_delete(sender, instance, **kwargs):  # pragma: no cover - signal
    if sender is None:
        return
    try:
        from forge.main.models.policy import Policy
    except Exception:
        return
    if not isinstance(instance, Policy):
        return
    remove_policy(instance.id)


# Wire up the receivers — connecting to None means "any sender"; we filter
# inside the handler to avoid an import-time dependency on the model.
post_save.connect(_on_policy_save)
post_delete.connect(_on_policy_delete)
