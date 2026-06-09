"""WebAuthn / FIDO2 API views.

Provides four flows:
  * register/begin   -> options for navigator.credentials.create()
  * register/complete -> verify attestation, store credential
  * authenticate/begin -> options for navigator.credentials.get()
  * authenticate/complete -> verify assertion, log the user in
                              (or mark MFA as satisfied for the session)

Plus a small CRUD surface for users to view, rename, delete their
own credentials.
"""

import base64
import logging
from datetime import timedelta

from django.contrib.auth import login
from django.contrib.auth.models import User
from django.utils.timezone import now

from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response

from forail.api.generics import APIView, ListAPIView
from forail.main.models.webauthn import (
    WebAuthnCredential,
    WebAuthnRegistrationChallenge,
    WebAuthnAuthenticationChallenge,
    is_replay,
)

logger = logging.getLogger('forail.api.views.webauthn')

CHALLENGE_TTL_SECONDS = 300  # 5 minutes


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def _b64u_decode(s: str) -> bytes:
    pad = '=' * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _rp_id(request):
    """Relying-party ID = host without port."""
    host = request.get_host()
    return host.split(':')[0]


def _origin(request):
    """Trusted origin for assertion verification."""
    return request.build_absolute_uri('/').rstrip('/')


def _purge_expired_challenges():
    cutoff = now()
    WebAuthnRegistrationChallenge.objects.filter(expires_at__lt=cutoff).delete()
    WebAuthnAuthenticationChallenge.objects.filter(expires_at__lt=cutoff).delete()


# ---------------------------------------------------------------------------
# Credential CRUD (own credentials only)
# ---------------------------------------------------------------------------

class WebAuthnCredentialList(ListAPIView):
    permission_classes = [IsAuthenticated]
    model = WebAuthnCredential

    def get_queryset(self):
        return WebAuthnCredential.objects.filter(user=self.request.user)

    def list(self, request, *args, **kwargs):
        creds = self.get_queryset()
        out = [
            {
                'id': c.id,
                'label': c.label,
                'transports': c.transports,
                'aaguid': c.aaguid,
                'created': c.created,
                'last_used_at': c.last_used_at,
                'sign_count': c.sign_count,
                'backup_eligible': c.backup_eligible,
                'backup_state': c.backup_state,
            }
            for c in creds
        ]
        return Response({'count': len(out), 'next': None, 'previous': None, 'results': out})


class WebAuthnCredentialDetail(APIView):
    permission_classes = [IsAuthenticated]

    def _get(self, request):
        try:
            return WebAuthnCredential.objects.get(pk=self.kwargs['pk'], user=request.user)
        except WebAuthnCredential.DoesNotExist:
            return None

    def patch(self, request, *args, **kwargs):
        cred = self._get(request)
        if cred is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        label = (request.data or {}).get('label')
        if label is not None:
            cred.label = str(label)[:128]
            cred.save(update_fields=['label', 'modified'])
        return Response({'id': cred.id, 'label': cred.label})

    def delete(self, request, *args, **kwargs):
        cred = self._get(request)
        if cred is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        cred.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class WebAuthnRegisterBegin(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
            from webauthn import generate_registration_options, options_to_json
            from webauthn.helpers.structs import (
                AuthenticatorSelectionCriteria,
                ResidentKeyRequirement,
                UserVerificationRequirement,
            )
        except ImportError:
            return Response(
                {'detail': 'webauthn package is not installed.'},
                status=status.HTTP_501_NOT_IMPLEMENTED,
            )

        _purge_expired_challenges()
        user = request.user

        existing = list(
            WebAuthnCredential.objects.filter(user=user).values_list('credential_id', flat=True)
        )

        opts = generate_registration_options(
            rp_id=_rp_id(request),
            rp_name='Forail Platform',
            user_id=str(user.id).encode('utf-8'),
            user_name=user.username,
            user_display_name=user.get_full_name() or user.username,
            exclude_credentials=[
                {'id': bytes(c), 'type': 'public-key'} for c in existing
            ],
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.PREFERRED,
                user_verification=UserVerificationRequirement.PREFERRED,
            ),
        )

        WebAuthnRegistrationChallenge.objects.create(
            user=user,
            challenge=opts.challenge,
            expires_at=now() + timedelta(seconds=CHALLENGE_TTL_SECONDS),
        )

        import json
        return Response(json.loads(options_to_json(opts)))


class WebAuthnRegisterComplete(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
            from webauthn import verify_registration_response
        except ImportError:
            return Response(
                {'detail': 'webauthn package is not installed.'},
                status=status.HTTP_501_NOT_IMPLEMENTED,
            )

        user = request.user
        body = request.data or {}
        label = (body.get('label') or '').strip()[:128]
        credential = body.get('credential')
        if not credential:
            return Response({'detail': 'Missing credential payload.'}, status=400)

        # Find latest unexpired challenge for this user
        challenge_obj = (
            WebAuthnRegistrationChallenge.objects
            .filter(user=user, expires_at__gte=now())
            .order_by('-created_at')
            .first()
        )
        if challenge_obj is None:
            return Response({'detail': 'Registration challenge expired or missing.'}, status=400)

        try:
            verification = verify_registration_response(
                credential=credential,
                expected_challenge=bytes(challenge_obj.challenge),
                expected_origin=_origin(request),
                expected_rp_id=_rp_id(request),
            )
        except Exception as e:
            logger.warning('WebAuthn registration verification failed: %s', e)
            return Response({'detail': f'Verification failed: {e}'}, status=400)

        cred = WebAuthnCredential.objects.create(
            user=user,
            credential_id=verification.credential_id,
            public_key=verification.credential_public_key,
            sign_count=verification.sign_count,
            label=label or 'Security key',
            aaguid=str(getattr(verification, 'aaguid', '') or ''),
            backup_eligible=getattr(verification, 'credential_backed_up', False) or False,
            backup_state=getattr(verification, 'credential_backed_up', False) or False,
            transports=(credential.get('response', {}) or {}).get('transports') or [],
        )
        challenge_obj.delete()

        return Response({'id': cred.id, 'label': cred.label}, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# Authentication / assertion
# ---------------------------------------------------------------------------

class WebAuthnAuthenticateBegin(APIView):
    """Anyone can begin — used both for first-factor passwordless and MFA."""
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        try:
            from webauthn import generate_authentication_options, options_to_json
            from webauthn.helpers.structs import UserVerificationRequirement
        except ImportError:
            return Response(
                {'detail': 'webauthn package is not installed.'},
                status=status.HTTP_501_NOT_IMPLEMENTED,
            )

        _purge_expired_challenges()
        body = request.data or {}
        username = (body.get('username') or '').strip()

        user = None
        allow_credentials = []
        if username:
            try:
                user = User.objects.get(username=username)
                allow_credentials = [
                    {'id': bytes(c), 'type': 'public-key'}
                    for c in WebAuthnCredential.objects.filter(user=user).values_list(
                        'credential_id', flat=True
                    )
                ]
            except User.DoesNotExist:
                # Don't leak whether the user exists; emit empty allow list.
                pass

        opts = generate_authentication_options(
            rp_id=_rp_id(request),
            allow_credentials=allow_credentials,
            user_verification=UserVerificationRequirement.PREFERRED,
        )

        WebAuthnAuthenticationChallenge.objects.create(
            user=user,
            challenge=opts.challenge,
            expires_at=now() + timedelta(seconds=CHALLENGE_TTL_SECONDS),
        )

        import json
        return Response(json.loads(options_to_json(opts)))


class WebAuthnAuthenticateComplete(APIView):
    """Verify assertion. If session has `webauthn_pending`, mark MFA as satisfied.
    Otherwise (passwordless flow), log the matched user in."""
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        try:
            from webauthn import verify_authentication_response
        except ImportError:
            return Response(
                {'detail': 'webauthn package is not installed.'},
                status=status.HTTP_501_NOT_IMPLEMENTED,
            )

        body = request.data or {}
        credential = body.get('credential')
        if not credential:
            return Response({'detail': 'Missing credential payload.'}, status=400)

        # Locate the credential by raw ID
        try:
            raw_id = _b64u_decode(credential.get('rawId') or credential.get('id'))
        except Exception:
            return Response({'detail': 'Invalid credential id encoding.'}, status=400)

        try:
            stored = WebAuthnCredential.objects.select_related('user').get(credential_id=raw_id)
        except WebAuthnCredential.DoesNotExist:
            return Response({'detail': 'Unknown credential.'}, status=400)

        # Find a fresh challenge for the matching user (or any user-less one)
        challenge_obj = (
            WebAuthnAuthenticationChallenge.objects
            .filter(expires_at__gte=now())
            .filter(user__in=[stored.user, None])
            .order_by('-created_at')
            .first()
        )
        if challenge_obj is None:
            return Response({'detail': 'Authentication challenge expired or missing.'}, status=400)

        try:
            verification = verify_authentication_response(
                credential=credential,
                expected_challenge=bytes(challenge_obj.challenge),
                expected_origin=_origin(request),
                expected_rp_id=_rp_id(request),
                credential_public_key=bytes(stored.public_key),
                credential_current_sign_count=stored.sign_count,
            )
        except Exception as e:
            logger.warning('WebAuthn assertion verification failed: %s', e)
            return Response({'detail': f'Verification failed: {e}'}, status=400)

        # Replay protection guard
        if is_replay(stored.sign_count, verification.new_sign_count):
            logger.warning(
                'WebAuthn replay detected for user=%s cred=%s', stored.user_id, stored.id
            )
            return Response({'detail': 'Replay detected.'}, status=400)

        stored.sign_count = verification.new_sign_count
        stored.last_used_at = now()
        stored.save(update_fields=['sign_count', 'last_used_at', 'modified'])
        challenge_obj.delete()

        # Branch: MFA-pending session vs passwordless first-factor
        session = request.session
        if session.get('mfa_pending') and session.get('mfa_pending_user') == stored.user_id:
            session['mfa_pending'] = False
            session.pop('mfa_pending_user', None)
            session.modified = True
            return Response({'mfa_satisfied': True, 'username': stored.user.username})

        # Passwordless first-factor: actually log the user in
        login(request, stored.user, backend='django.contrib.auth.backends.ModelBackend')
        return Response({'logged_in': True, 'username': stored.user.username})
