# 25 — What Forail Changed Relative to AWX

Forail is a fork of **AWX 24.6.1**, the last AWX release (2 July 2024). This
page answers the first question anyone evaluating a fork should ask — *what
did you actually change?* — with numbers you can reproduce, not adjectives.

Measured on 2026-10-06 against the `awx/` package of the `24.6.1` tag, with the
`forail/` package of `forail-backend` `develop` plus the October fixes. Paths
are compared after the `awx → forail` rename; file contents are compared with
the names `awx`, `forail`, `forge` and `tower` masked, so a renamed identifier
is not counted as a change. The script is at the end of this page.

## In one table

| | Files |
|---|---:|
| AWX files kept byte-for-byte (modulo the rename) | 869 |
| AWX files modified | 63 |
| AWX files removed | 1,719 |
| Files added by Forail | 179 |

Of the 1,719 removed files, **1,707 are the legacy AWX React UI**
(`awx/ui/src`), which AWX itself had replaced and which Forail never built. The
Forail UI is a separate project, [forail-frontend](https://github.com/forail-platform/forail-frontend).

Of the 179 added files, 177 are Python, about 31,700 lines. A share of that is
reorganisation, not new behaviour: AWX's 3,000-line `main/access.py`, 6,300-line
`api/serializers.py` and 4,600-line `api/views/__init__.py` are split into
packages by domain. The rest is the features below.

## What Forail adds

Lines of application code (models, API, tasks, engine) and the number of test
functions that exercise it.

| Feature | Code (lines) | Tests | Docs |
|---|---:|---:|---|
| Event-driven automation — inbound webhooks to job launches, plus outbound webhooks on job events | 1,525 | 45 | [Event-Driven Automation](15-event-driven-automation.md) |
| Drift detection — fact snapshots after each job, diffs, alert rules | 1,472 | 41 | [Drift Detection](16-drift-detection.md) |
| Multi-tenancy — quotas, branding, row-level security, isolation audit | 2,076 | 90 | [Multi-Tenancy](22-multi-tenancy.md) |
| Self-service catalog — request, approve, launch | 1,404 | 22 | [Self-Service Portal](17-self-service-portal.md) |
| IaC and supply-chain scanning | 1,175 | 30 | [IaC Scanning](20-iac-scanning.md) |
| Policy-as-code with Open Policy Agent | 937 | 19 | [Policy-as-Code](19-policy-as-code.md) |
| Observability — OpenTelemetry traces and metrics | 770 | 32 | [Observability](21-observability.md) |
| WebAuthn passkeys and OIDC additions | 550 | 16 | [OIDC + WebAuthn](18-oidc-webauthn.md) |
| Audit trail (`AuditEvent`) | 514 | 6 | [Audit Trail](14-audit-trail.md) |
| Recommendations | 480 | 29 | [Recommendations](23-recommendations.md) |
| AWX → Forail importer (`import_from_awx`) | 871 | 27 | [AWX → Forail Migration](24-awx-import.md) |

Plus 17 database migrations, and access rules for the new configuration
objects (event rules, outbound webhooks, drift alert rules, policies, scanners,
catalog items) with 26 role-by-role API tests.

## What Forail changed in AWX's own code

63 AWX files differ. The changes, by size:

- **Settings** (`main/conf.py`, `sso/conf.py`, `settings/production.py`) —
  registrations for the new features (OPA, drift, tenancy, observability) and
  secure-by-default SAML: signed responses *and* assertions, SHA-256, no
  unsolicited responses. That SAML default is a breaking change for IdPs that
  send unsigned or SHA-1 assertions; see the 2026.07.0 release notes.
- **Signals** (`main/signals.py`) — every superuser grant or revoke is recorded
  in the audit log, independently of the activity stream; the activity stream
  covers the new configuration objects and keeps their secrets out.
- **Middleware** (`main/middleware.py`) — request context for the audit trail;
  `X-Forwarded-For` is trusted only from configured proxies, so a client cannot
  forge the recorded IP.
- **Models** (workflow, inventory, jobs, organization, credential, …) — node
  surveys on workflow nodes, tenancy fields on organizations, small fixes.
- **Session and token handling** — session keys hashed at rest, refresh tokens
  redacted from logs, superuser-grant audit (the 2026.07.0 security release).
- **Everything else** in the list is a handful of lines: entry points, URL
  wiring, version strings.

The full list, with changed-line counts, comes out of the script below.

## What did not change

- **The REST API.** It is still `/api/v2/`, and the unmodified AWX clients —
  `awxkit` 24.6.1 (the `awx` CLI) and the `awx.awx` 24.6.1 Ansible collection —
  pass against Forail with no failures. That check runs nightly in CI
  (`.github/workflows/awx-compat.yml`).
- **The job engine** — dispatcher, task manager, Receptor, execution
  environments — is AWX's, with the AWX tests that cover it.
- **The database schema** for everything AWX already had. Forail adds tables;
  an AWX 24.6.1 installation can be migrated with `import_from_awx`.

## What is known not to be right yet

Honesty is cheaper before somebody else finds it.

- **Until the October 2026 fixes, several headline features did not work in
  the published images.** EDA and drift imported `celery`, which Forail does not
  ship, so no event rule ever fired and no drift snapshot was ever taken;
  outbound webhooks were never sent; the WebAuthn library was missing from the
  image. Each now has an end-to-end test and a guard that fails the build when
  Forail's code imports a package the image lacks.
- The **third-party license texts** (`licenses/`) were not carried over when the
  backend was split out of the AWX monorepo. The license check test is
  disabled until they are restored.
- Some Forail models have **drifted from their migrations** (index names, field
  options): `makemigrations --check` is not clean. No data is affected; it has
  to be reconciled before the next schema change to those models.
- The read-only scan and tenancy records have no per-object access rules or
  detail endpoints yet.

## Reproducing the numbers

```bash
git clone --depth 1 --branch 24.6.1 https://github.com/ansible/awx.git awx-24.6.1
git clone https://github.com/forail-platform/forail-backend.git
python3 - <<'EOF'
import os, re
up, fo = 'awx-24.6.1/awx', 'forail-backend/forail'
mask = lambda b: re.sub(rb'(?i)forail|awx|forge|tower', b'X', b)
def walk(root):
    return {os.path.relpath(os.path.join(d, f), root): os.path.join(d, f)
            for d, _, fs in os.walk(root) if '__pycache__' not in d for f in fs}
a, b = walk(up), walk(fo)
common = a.keys() & b.keys()
modified = [p for p in common if mask(open(a[p], 'rb').read()) != mask(open(b[p], 'rb').read())]
print('kept', len(common) - len(modified), 'modified', len(modified),
      'removed', len(a.keys() - b.keys()), 'added', len(b.keys() - a.keys()))
EOF
```
