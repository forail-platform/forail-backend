# 24 — AWX → Forail Importer

`import_from_awx` is a one-shot, idempotent management command that migrates
configuration from an existing **AWX** (or **AAP**) installation into Forail via
the source's REST API. It exists so teams can move to Forail without rebuilding
organizations, inventories, credentials and templates by hand.

## Usage

```bash
forail-manage import_from_awx \
    --url https://awx.example.com \
    --token "$AWX_TOKEN" \
    --dry-run
```

| Option                  | Description                                                            |
| ----------------------- | ---------------------------------------------------------------------- |
| `--url`                 | Base URL of the source AWX install (required).                         |
| `--token`               | OAuth2 token for the source AWX API (preferred auth).                  |
| `--username/--password` | Basic auth, if no token.                                               |
| `--insecure`            | Skip source TLS certificate verification.                              |
| `--dry-run`             | Fetch and report what would change, then roll back without writing.    |
| `--resource <type>`     | Limit to specific resource type(s); repeatable. Default: all.          |

Resource types (and import order): `organizations`, `users`, `teams`,
`credential_types`, `credentials`, `projects`, `inventories`, `groups`,
`hosts`, `inventory_sources`, `job_templates`, `workflow_job_templates`,
`workflow_nodes`, `notification_templates`, `schedules`, `roles`.

## What it imports

- **Organizations** — name, description, `max_hosts`.
- **Users** — username, name, email, `is_superuser`. Created with an **unusable
  password** (passwords are not exported by AWX).
- **Teams** — within their organization.
- **Credential Types** — custom (non-managed) types only; managed types already
  ship with Forail and are matched by name.
- **Credentials** — structure + non-secret inputs (see *Secrets* below).
- **Projects** — SCM settings (type, URL, branch, refspec, update flags, etc.).
- **Inventories** — variables, kind, host filter.
- **Groups** — including the parent/child group hierarchy.
- **Hosts** — including group membership.
- **Inventory Sources** — source type/path/vars, SCM branch, overwrite and
  verbosity options, `update_on_launch`, the source project, and source
  credentials.
- **Job Templates** — playbook, inventory, project, launch/`ask_*` flags,
  survey spec, and associated credentials.
- **Workflow Job Templates** — extra vars, survey, limit/branch/tags, webhook
  service, optional inventory.
- **Workflow Nodes** — the full node graph: each node's
  `unified_job_template` target and the `success`/`failure`/`always` edges
  (wired in a second pass once every node exists).
- **Notification Templates** — type, non-secret configuration and custom
  messages, plus the `started`/`success`/`error` hooks on job templates,
  workflow templates, projects and inventory sources.
- **Schedules** — the iCal `rrule`, enabled flag and prompt-on-launch
  `extra_data`, attached to their job/workflow/project/inventory-source target.
- **RBAC role assignments** — which users and teams hold which roles. A user
  grant maps to `role.members.add(user)`; a team grant maps to
  `role.parents.add(team.member_role)` so the team inherits the role. Singleton
  system roles (`system_administrator`, `system_auditor`) are applied to the
  user directly.

## Idempotency

Re-running is safe. Objects are matched by natural key — name within
organization (username for users) — and **updated** rather than duplicated. An
`awx_id → Forail object` map is maintained during the run to resolve foreign
keys (e.g. a job template's inventory and project).

The whole run executes inside a single transaction with the activity stream
disabled (so the migration does not flood the audit log). `--dry-run` rolls the
transaction back at the end.

## ⚠️ Secrets are not migrated

The AWX REST API never returns secret credential inputs — it replaces them with
the literal `$encrypted$`. User passwords are likewise not exported. Therefore:

- Credential **structure** and any non-secret inputs are imported.
- Secret fields (passwords, SSH keys, tokens) are **dropped**, and the command
  prints how many secret fields need manual re-entry.
- Imported users have an unusable password until one is set (or SSO is used).

Plan to re-enter credential secrets in Forail after the import.

## Not imported by design

Job/workflow **run history** and ephemeral execution state are intentionally
out of scope — this command migrates *configuration*, not job results. Secret
values (credential inputs, notification tokens) cannot be exported by AWX and
must be re-entered, as described above.
