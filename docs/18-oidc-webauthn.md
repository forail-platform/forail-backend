# 18 — OIDC + WebAuthn

Modern SSO via OIDC and phishing-resistant authentication via WebAuthn
(FIDO2). Adds passwordless first-factor login, second-factor MFA, and
"Sign in with OIDC" alongside the existing form / LDAP / SAML / RADIUS
/ TACACS+ stack.

---

## Architecture

```
Login page
   │
   ├── Username + password ───► /api/login/ (form)         ┐
   │                                                       │
   ├── "Sign in with OIDC"  ───► /sso/login/oidc/          │   primary auth
   │                              (social-auth redirect)   │
   │                                                       │
   └── "Sign in with security key" (passwordless)          │
        │                                                  │
        ▼                                                  │
        /api/v2/webauthn/authenticate/begin/  -> options   │
        navigator.credentials.get() in browser             │
        /api/v2/webauthn/authenticate/complete/ -> login() ┘
                                                  │
                                                  ▼
                              WebAuthnMfaEnforcementMiddleware
                                                  │
              ┌───────────────────────────────────┼─────────────────────────┐
              │                                   │                         │
              ▼                                   ▼                         ▼
   org policy: none           org policy: admins/all             user already mfa_satisfied
   session.mfa_satisfied=user.id           session.mfa_pending=true        proceed
                                           session.mfa_pending_user=user.id
                                                  │
                                                  ▼
                                      Frontend interstitial /auth/mfa
                                                  │
                                /api/v2/webauthn/authenticate/{begin,complete}/
                                                  │
                                                  ▼
                                       session.mfa_pending=false → app
```

The OIDC client is the existing `social_core.backends.open_id_connect.OpenIdConnectAuth`
that AWX vendored. JIT user creation and org/team mapping reuse the
existing `forail/sso/social_pipeline.py`. We add a few extra settings
(button label, default scopes override, organization/team JSON maps)
and the frontend "Sign in with OIDC" button.

---

## WebAuthn models — `forail/main/models/webauthn.py`

### `WebAuthnCredential(CreatedModifiedModel)`

| Field                              | Notes                                               |
| ---------------------------------- | --------------------------------------------------- |
| `user`                             | FK auth.User (CASCADE)                              |
| `credential_id`                    | BinaryField unique — raw cred ID from authenticator |
| `public_key`                       | BinaryField — COSE pubkey                           |
| `sign_count`                       | Authenticator counter; replay protection            |
| `transports`                       | JSON list (`usb`/`nfc`/`ble`/`internal`/`hybrid`)   |
| `aaguid`                           | Authenticator AAGUID                                |
| `label`                            | User-facing nickname                                |
| `last_used_at`                     | Updated on every successful assertion               |
| `backup_eligible` / `backup_state` | Multi-device hint flags                             |

### Challenge models

`WebAuthnRegistrationChallenge` and `WebAuthnAuthenticationChallenge`
share `challenge` (random bytes), `created_at`, `expires_at`. TTL is
**5 minutes**, controlled by `CHALLENGE_TTL_SECONDS` in
`forail/api/views/webauthn.py`. Expired rows are purged opportunistically
on every begin call (`_purge_expired_challenges()`).

### Pure helpers (used by middleware + tested standalone)

```python
is_webauthn_required(setting, is_admin) -> bool
is_replay(stored_count, presented_count) -> bool
```

`is_replay` allows `(0, 0)` (some authenticators never bump the counter)
but rejects equal-or-decreasing counts otherwise.

---

## REST API

Mounted under `/api/v2/webauthn/`.

| Method | Path                     | Purpose                                                                                                                                                                           |
| ------ | ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GET    | `credentials/`           | List the calling user's credentials                                                                                                                                               |
| PATCH  | `credentials/{id}/`      | Rename (`{label}`)                                                                                                                                                                |
| DELETE | `credentials/{id}/`      | Delete                                                                                                                                                                            |
| POST   | `register/begin/`        | Returns `publicKeyCredentialCreationOptions` JSON; stores a fresh challenge                                                                                                       |
| POST   | `register/complete/`     | Verifies attestation with `webauthn.verify_registration_response`, persists the credential                                                                                        |
| POST   | `authenticate/begin/`    | Returns `publicKeyCredentialRequestOptions`. `username` body field optional (passwordless flows often omit it)                                                                    |
| POST   | `authenticate/complete/` | Verifies assertion via `verify_authentication_response`, runs `is_replay`, then either marks `session.mfa_pending=false` (MFA path) or calls Django `login()` (passwordless path) |

Origin and Relying-Party ID are derived from the request:

- `_origin(request)` = `request.build_absolute_uri('/').rstrip('/')`
- `_rp_id(request)` = `request.get_host().split(':')[0]`

This means the same image works on `https://localhost`,
`https://forail.example.com`, etc., without configuration.

---

## OIDC

### Settings (`forail/sso/conf.py`)

The four core OIDC settings already existed (legacy AWX heritage):

- `SOCIAL_AUTH_OIDC_KEY`, `SOCIAL_AUTH_OIDC_SECRET`
- `SOCIAL_AUTH_OIDC_OIDC_ENDPOINT`, `SOCIAL_AUTH_OIDC_VERIFY_SSL`

This feature adds four more under the same `oidc` category slug:

- `SOCIAL_AUTH_OIDC_BUTTON_LABEL` — text on the login page button.
- `SOCIAL_AUTH_OIDC_SCOPE` — list, default `['openid','profile','email']`.
- `SOCIAL_AUTH_OIDC_ORGANIZATION_MAP` — same shape as the SAML org map.
- `SOCIAL_AUTH_OIDC_TEAM_MAP` — same shape as the SAML team map.

### Backend wiring

The base `social_core.backends.open_id_connect.OpenIdConnectAuth` is
already wired into `AUTHENTICATION_BACKENDS` via the existing
"add backend if its required settings are present" pattern in
`forail/sso/fields.py`. The login URL is `/sso/login/oidc/` (handled by
`social-auth-app-django` URL routing — no new view needed).

A `ForailOIDCAuth` subclass is provided as a hook for future custom claim
mapping but is not currently registered.

---

## MFA enforcement middleware

`forail/main/middleware.py::WebAuthnMfaEnforcementMiddleware`

Runs after `AuthenticationMiddleware`. For every authenticated request:

1. Skip the WebAuthn endpoints themselves, `/api/login/`, `/api/logout/`,
   `/sso/`, `/api/v2/me/`, `/api/v2/ping/`, `/api/v2/config/`.
2. If `session['mfa_satisfied_for'] == user.id`, allow.
3. Iterate the user's organizations, fold over their `webauthn_required`
   setting via `is_webauthn_required(setting, is_admin)`.
4. If any org requires MFA and the session hasn't satisfied it yet:
   - `session['mfa_pending'] = True`
   - `session['mfa_pending_user'] = user.id`
   - Frontend reads this and navigates to `/auth/mfa`.

`Organization.webauthn_required` is a CharField with choices
`'none' / 'admins' / 'all'` (default `none`).

---

## Tests — `tests_standalone/test_webauthn.py`

16 tests, no Django bootstrap (uses module stubs the same way
`test_drift.py` and `test_service_catalog.py` do):

- Policy resolver: full `(setting, is_admin) → required` matrix.
- Replay guard: increasing / equal / decreasing / both-zero / zero→one.
- Challenge TTL arithmetic.
- URL-safe base64 round-trip helpers.

Run with: `python -m unittest tests_standalone.test_webauthn -v`

---

## End-to-end manual verification

Requires Chromium and either a hardware security key, Touch ID, or
Windows Hello. The browser only allows WebAuthn over HTTPS — use the
deployment behind nginx.

1. Open `/me/security`, name a credential, click **Add**, complete the
   browser prompt → credential appears in the list.
2. Log out, reload the login page, click **Sign in with security key**
   after typing your username → browser prompt → logged in.
3. PATCH an organization's `webauthn_required` to `admins`. Log in as
   an admin without credentials → server flips `mfa_pending`, frontend
   redirects to `/auth/mfa` → can't proceed without enrollment.
4. Configure Settings → Generic OIDC with a Keycloak realm; the login
   page now shows **Sign in with OIDC** which redirects to
   `/sso/login/oidc/`.
5. Negative path: tamper with `sign_count` in the DB to be lower than
   what the authenticator presents → assertion rejected with
   `Replay detected.`
