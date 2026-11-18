# 26 — Monitored servers

A **monitored server** is a host that runs `forail-agent` and reports metrics
and logs to the Forail Mobile backend, where people follow it from their phone.
Since forail-mobile#52 the platform is the source of truth for *which* servers
exist and *who* may reach them; the mobile backend keeps the telemetry and the
agent's token.

Any user can register their own server. Access follows Forail RBAC.

| Role                          | View server, metrics, logs | Rotate token / delete | Grant / revoke access |
| ----------------------------- | -------------------------- | --------------------- | --------------------- |
| Owner (registered it)         | yes                        | yes                   | no                    |
| Admin of its organization     | yes                        | yes                   | yes                   |
| Superuser                     | yes                        | yes                   | yes                   |
| Granted `read_role`           | yes                        | no                    | no                    |
| Organization or system auditor| yes (read only)            | no                    | no                    |
| Anyone else                   | `404`                      | —                     | —                     |

The owner holds `admin_role` on their server, which on other resources would
let them share it. Here sharing is an organization decision: granting or
revoking a role on a monitored server takes an admin of its organization or a
superuser, through `/api/v2/users/{id}/roles/`, `/api/v2/teams/{id}/roles/`
and django-ansible-base's `/api/v2/role_user_assignments/` alike.

Everything a user may not read answers `404` — the list leaves it out, and the
detail, access list, object roles, activity stream, enrollment code and rotate
endpoints all say *not found* — so the API never confirms a server exists.

---

## How the pieces talk

```
  Forail UI / API client                    phone (Forail Mobile app)
          │                                           │
          ▼                                           ▼
  ┌──────────────────────┐   service API    ┌──────────────────────────┐
  │ Forail platform      │ ───────────────▶ │ Forail Mobile backend     │
  │  MonitoredServer     │  create, code,   │  servers, agent tokens,   │
  │  admin_role/read_role│  rotate, delete, │  metrics, logs            │
  │                      │  status          │                           │
  │                      │ ◀─────────────── │  "which servers may user  │
  │                      │  visible/access  │   N read?" (cached ≤ 60 s)│
  └──────────────────────┘                  └──────────────────────────┘
                                                        ▲
                                     forail-agent enroll│ --code fme_…
                                                        │
                                                 monitored server
```

Both directions authenticate with **one shared secret**,
`FORAIL_MOBILE_SERVICE_TOKEN`, sent as `Authorization: Service <token>`. The
service endpoints accept nothing else: a user's session, token or Basic
credentials get `403`.

The platform **never shows a long-lived agent token**. Registering a server
and rotating its token both end in a one-time enrollment code (ten minutes,
single use) that the agent exchanges for its token on the host itself.

---

## API

### `/api/v2/monitored_servers/`

| Method | Path                         | Who                         | Notes |
| ------ | ---------------------------- | --------------------------- | ----- |
| GET    | `/`                          | anyone                      | filtered by RBAC; `online` / `last_report_at` from the mobile backend, `null` when it cannot be asked |
| POST   | `/`                          | any member of the organization | `{name, organization, description?}`; the caller becomes the owner |
| GET    | `/{id}/`                     | readers                     | |
| PATCH  | `/{id}/`                     | owner, org admin, superuser | `description` only; `name` and `organization` are fixed |
| DELETE | `/{id}/`                     | owner, org admin, superuser | removes it from the mobile backend first; `503` if that fails |
| POST   | `/{id}/enrollment_code/`     | owner, org admin, superuser | `{code, expires_at, api_url, command}` |
| POST   | `/{id}/rotate_token/`        | owner, org admin, superuser | revokes the agent's token, returns a code like the above; the agent stops reporting until it re-enrolls |
| GET    | `/{id}/access_list/`         | readers                     | standard Forail access list |
| GET    | `/{id}/object_roles/`        | readers                     | `admin_role`, `read_role` — grant with `POST /api/v2/users/{id}/roles/` |
| GET    | `/{id}/activity_stream/`     | readers                     | |

`summary_fields.user_capabilities` carries `edit`, `delete`, `rotate` and
`manage_access`, so a UI shows exactly the buttons the user may press.

Errors:

| Status | When |
| ------ | ---- |
| `400`  | invalid name (`^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$` — it travels into signed approvals), or the name is taken in that organization |
| `403`  | not a member of the organization (create); not allowed to change it |
| `404`  | the server is not visible to you |
| `409`  | `MONITORED_SERVERS_PER_USER` reached, or the mobile backend already has that name in the organization |
| `503`  | the mobile backend is not configured or not reachable |

The same name may be used in different organizations.

Example — register a server and get the install command:

```bash
curl -s -u alice:… -X POST https://forail.example.com/api/v2/monitored_servers/ \
  -H 'Content-Type: application/json' -d '{"name": "web-01", "organization": 2}'
# {"id": 7, "name": "web-01", "owner": 12, "mobile_server_id": "8b1f…", …}

curl -s -u alice:… -X POST https://forail.example.com/api/v2/monitored_servers/7/enrollment_code/
# {"code": "fme_…", "expires_at": "2026-11-03T10:20:00Z",
#  "command": "sudo forail-agent enroll --api https://mobile.example.com --code fme_…"}
```

### Service endpoints (for the Forail Mobile backend)

| Path | Answers |
| ---- | ------- |
| `GET /api/v2/monitored_servers/service/visible/?user=<platform user id>` | `{"user": 12, "results": [{"mobile_server_id": "…", "role": "admin" \| "read"}]}` |
| `GET /api/v2/monitored_servers/service/access/?server=<mobile server id>` | `{"server", "name", "organization", "results": [{"username", "role", "source"}]}` with `source` one of `superuser`, `owner`, `org_admin`, `granted`, `team`, `org_auditor` |

With `FORAIL_MOBILE_SERVICE_TOKEN` empty both answer `404`.

---

## Audit

The activity stream records create, delete, description changes, every
enrollment code issued (`{"enrollment_code": "issued"}`), every rotation
(`{"agent_token": "rotated"}`) and every role grant and revoke, each with the
user who did it.

---

## Configuration

See doc 12, *Forail Mobile*. In short:

```python
# /etc/tower/conf.d/forail_mobile.py  (or the same names as environment variables)
FORAIL_MOBILE_URL = 'http://forail-mobile-backend:8080'      # in-cluster
FORAIL_MOBILE_PUBLIC_URL = 'https://mobile.example.com'      # what agents use
FORAIL_MOBILE_SERVICE_TOKEN = '<same value as the mobile backend>'
MONITORED_SERVERS_PER_USER = 10
```

---

## Upgrading

Migration 0213 adds the table, its row-level security policy and the managed
role definitions (`MonitoredServer Admin`, `Organization MonitoredServer
Admin`), and adds the new permissions to `Organization Admin`, `Organization
Audit` and the migrated `System Auditor`. It deletes no role definition.

Two things were found only by running the migrations on a real database, not
by the functional suite (which runs without them), and are fixed:

- the earlier RLS migrations (0206, 0210, 0211) built their SQL from the live
  table list and failed on a table created later; each now takes
  `rls_tables_direct_until(<its number>)`;
- re-running `setup_managed_role_definitions` deleted the migrated `System
  Auditor` role and every system auditor's assignment; 0213 uses
  `sync_managed_role_definitions`, which deletes nothing.

Verified on 2026-11-17/18 by upgrading the dev cluster from 0210 and by
migrating an empty database from 0001, both on PostgreSQL. The whole
"done when" of forail-mobile#52 then ran against the cluster with
`forail-mobile/tools/epic52-live-check.py`: 54 of 54 checks.

---

## Moving servers registered before #52

Servers that were registered directly in the Forail Mobile backend have no
platform record, so after the upgrade nobody but a superuser sees them in the
app. Bring them under platform RBAC with:

```bash
forail-manage import_monitored_servers --organization Default --owner admin --grant-members --dry-run
forail-manage import_monitored_servers --organization Default --owner admin --grant-members
```

Each unknown server gets a `MonitoredServer` in that organization, owned by
`--owner`; `--grant-members` gives every user on the server's old member list
`read_role` (matched by their platform id). Servers already linked are
skipped, so the command can be re-run. A server's organization cannot change
later, so when servers belong to different organizations, import them in
groups with `--only`:

```bash
forail-manage import_monitored_servers --organization Shop --owner ana --only web-01,web-02
```

The mobile backend's old `server_members` table is no longer read once the
platform decides visibility; it stays in place for this import and is dropped
in a later release.
