# 05 — Authentication & RBAC

Forail supports multiple authentication methods and has a powerful role-based
access control system. This document covers how users authenticate and how
permissions work.

---

## Authentication Methods

| Method              | Used for                 | How it works                             |
| ------------------- | ------------------------ | ---------------------------------------- |
| Session (cookie)    | Browser UI               | Login form → session cookie              |
| OAuth2 Bearer Token | API clients, scripts     | `Authorization: Bearer <token>`          |
| Basic Auth          | Simple API calls         | `Authorization: Basic base64(user:pass)` |
| LDAP                | Enterprise directory     | Bind to LDAP server, map groups          |
| SAML 2.0            | Enterprise SSO           | SAML assertion from Identity Provider    |
| Social Auth         | GitHub, Google, Azure AD | OAuth2 flow with provider                |
| RADIUS              | Network authentication   | RADIUS server                            |

---

## Session Authentication (Browser)

The user logs in with username/password and receives two cookies:

- `awx_sessionid` — HttpOnly, Secure. JS cannot read it.
- `csrftoken` — JS reads it and sends it as the `X-CSRFToken` header on every POST/PATCH/DELETE.

**Watch out:**

- Sessions last **30 minutes** (default). Every request resets the timer.
- `SESSION_COOKIE_SECURE=True` — the cookie is only sent over HTTPS. If you're testing
  on HTTP, login won't work. Set to `False` for local development.

---

## OAuth2 Token (API)

For scripts, automation, and integrations.

### Creating a token

```bash
# Via CLI
forail-manage create_oauth2_token --user=admin

# Via API
curl -u admin:password -X POST \
  -H 'Content-Type: application/json' \
  -d '{"scope": "write"}' \
  https://forail.example.com/api/v2/tokens/
```

### Usage

```bash
curl -H 'Authorization: Bearer <token>' \
  https://forail.example.com/api/v2/job_templates/
```

**Watch out:**

- Token scope: `read` (GET only) or `write` (everything)
- Default token expiry is very long (~1000 years). For security, rotate tokens
  periodically and delete old ones: `forail-manage cleanup_tokens`

---

## SSO — LDAP

LDAP is configured via the API: `PATCH /api/v2/settings/ldap/`

### What happens during LDAP login

1. User enters username/password in the Forail login form
2. Forail connects to the LDAP server with a service account
3. Searches for the user's DN based on `AUTH_LDAP_USER_SEARCH`
4. Attempts to bind as the user with the entered password
5. If successful — maps LDAP attributes to Django user fields
6. Applies organization/team mapping from LDAP groups
7. Creates/updates the local user record
8. Creates a session

### Watch out

- **`AUTH_LDAP_SERVER_URI`** — Use `ldaps://` (port 636) for production.
  `ldap://` (port 389) sends passwords in plaintext.

- **Organization/Team Map** — Maps LDAP groups to Forail organizations and teams.
  `remove_users: true` means users NOT in the LDAP group will be **removed**
  from the organization on their next login. Be careful with this.

- **Multiple LDAP servers** — Forail supports up to 5 LDAP servers (AUTH_LDAP_1 through AUTH_LDAP_5).
  Each has its own configuration.

---

## SSO — SAML 2.0

Configured via: `PATCH /api/v2/settings/saml/`

You need to define:

- SP (Service Provider) Entity ID, certificate, and key
- IDP (Identity Provider) configuration: entity_id, SSO URL, X.509 certificate
- Attribute mapping: which SAML attributes correspond to email, name, etc.

**Watch out:**

- The SAML metadata endpoint is at `https://forail.example.com/sso/metadata/saml/`
  — give this to your IDP for automatic configuration.
- SAML requires valid HTTPS certificates on both sides.

---

## SSO — Social Auth (GitHub, Google, Azure AD)

Configured via: `PATCH /api/v2/settings/github/` (or `google-oauth2/`, `azuread-oauth2/`)

You need:

- Client ID and Secret from the OAuth2 provider
- Organization/Team mapping (optional)

**Watch out:**

- The callback URL you must register with the provider:
  `https://forail.example.com/sso/complete/github-org/`
- GitHub Enterprise has separate configuration with custom URLs.

---

## RBAC — Role-Based Access Control

### Concept

Every resource (template, inventory, credential...) has **roles**.
Users and teams are assigned to roles to gain access.

### Role Types

| Role            | What it allows                                 |
| --------------- | ---------------------------------------------- |
| `admin_role`    | Full CRUD access to the resource               |
| `read_role`     | Read-only access                               |
| `use_role`      | Use the resource (e.g., a credential in a job) |
| `execute_role`  | Launch/run the template                        |
| `update_role`   | Trigger updates (project sync, inventory sync) |
| `adhoc_role`    | Run ad-hoc commands on inventory               |
| `approval_role` | Approve workflow approval nodes                |

### System-Wide Roles

| Role                   | Scope                                 |
| ---------------------- | ------------------------------------- |
| `system_administrator` | Full access to EVERYTHING (superuser) |
| `system_auditor`       | Read-only access to EVERYTHING        |

### Hierarchy — How roles are inherited

```
System Administrator
    └── Organization Admin
        ├── Organization Member → Organization Read
        ├── Project Admin → Project Use, Update
        ├── Inventory Admin → Inventory Use, Ad Hoc, Update
        ├── Credential Admin → Credential Use
        ├── Job Template Admin → Execute
        └── Workflow Admin → Execute

System Auditor
    └── Organization Auditor → Read-only on everything in the org
```

**Key point:** If you're an org admin, you automatically get admin access to ALL resources
within that organization. You don't need to add roles individually.

### Watch out

- **RBAC filters API results.** When a regular user calls `GET /api/v2/job_templates/`,
  they only see templates they have `read_role` on. An admin sees everything.

- **Credential `use_role` ≠ `read_role`.** A user with `use_role` can use the
  credential in a job, but CANNOT see secret field values. This is by design —
  an operator can run a job without knowing the SSH key.

- **Team role inheritance.** When you assign a role to a team, ALL team members get that role.
  Adding/removing a team member automatically changes their permissions.

- **`is_system_auditor` flag.** Doesn't use the role system — it's set directly on
  the User object. An auditor sees everything but cannot change anything.

---

## Practical Examples

### Give a user access to run a specific template

```bash
# 1. Find the role IDs on the template
curl -u admin:password \
  https://forail.example.com/api/v2/job_templates/5/ \
  | jq '.summary_fields.object_roles'

# 2. Assign execute_role (e.g., ID 43) to user (ID 7)
curl -u admin:password -X POST \
  -H 'Content-Type: application/json' \
  -d '{"id": 7}' \
  https://forail.example.com/api/v2/roles/43/users/
```

### Give a team admin access to an inventory

```bash
# Find the admin_role ID on the inventory, then assign the team
curl -u admin:password -X POST \
  -H 'Content-Type: application/json' \
  -d '{"id": 3}' \
  https://forail.example.com/api/v2/roles/55/teams/
```

### Create a read-only auditor user

```bash
curl -u admin:password -X POST \
  -H 'Content-Type: application/json' \
  -d '{"username": "auditor", "password": "Pass123!", "is_system_auditor": true}' \
  https://forail.example.com/api/v2/users/
```

### Check what access a user has

```bash
# All roles for a user
curl -u admin:password https://forail.example.com/api/v2/users/7/roles/

# Can the user launch a template?
curl -u user7:password https://forail.example.com/api/v2/job_templates/5/launch/
# 200 = yes, 403 = no execute_role
```

---

## Watch Out — Common Mistakes

1. **Forgotten organization.** You create a template but the user can't see it. Check
   that the user has at least `member_role` on the organization.

2. **LDAP `remove_users: true`.** This will remove users from the organization if they're
   not in the LDAP group. The user can lose access to everything. Start with `false` until you test.

3. **OAuth2 token for SSO users.** By default, SSO users CANNOT create OAuth2 tokens.
   Enable `ALLOW_OAUTH2_FOR_EXTERNAL_USERS` if needed.

4. **Session timeout.** Default is 30 minutes. For users who work longer sessions,
   increase `SESSION_COOKIE_AGE` via the API.
