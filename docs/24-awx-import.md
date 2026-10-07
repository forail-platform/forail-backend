# 24 — AWX → Forail Importer

`import_from_awx` is a one-shot, idempotent management command that migrates
configuration from an existing **AWX** (or **AAP**) installation into Forail via
the source's REST API. It exists so teams can move to Forail without rebuilding
organizations, inventories, credentials and templates by hand.

## Usage

Review first, then import:

```bash
# 1. Dry run: nothing is written; the report lists every object by name.
forail-manage import_from_awx \
    --url https://awx.example.com \
    --token-file /run/secrets/awx-token \
    --dry-run --report-file /tmp/awx-import-plan.json

# 2. The real run, with the same options minus --dry-run.
forail-manage import_from_awx \
    --url https://awx.example.com \
    --token-file /run/secrets/awx-token \
    --report-file /tmp/awx-import-result.json
```

| Option                  | Description                                                            |
| ----------------------- | ---------------------------------------------------------------------- |
| `--url`                 | Base URL of the source AWX install (required).                         |
| `--token-file`          | File holding the OAuth2 token. The safest option: nothing in `ps`, the environment or shell history. |
| `--password-file`       | File holding the basic-auth password.                                  |
| `--username`            | Basic-auth user, if no token (or `AWX_USERNAME`).                      |
| `--token` / `--password`| **Deprecated** — visible in `ps` / `/proc` and shell history. Still accepted, with a warning. |
| `--insecure`            | Skip source TLS certificate verification.                              |
| `--dry-run`             | Fetch and report what would change, then roll back without writing.    |
| `--report-file PATH`    | Also write the report as JSON (see [The report](#the-report)).         |
| `--grant-superusers`    | Honour `is_superuser` / system-role grants from the source (**off** by default). |
| `--trust-injectors`     | Import custom credential-type injectors verbatim (**off**; else re-approve). |
| `--resource <type>`     | Limit to specific resource type(s); repeatable. Default: all.          |

Secrets are read in this order: `--token-file` / `--password-file`, then the
`AWX_TOKEN` / `AWX_PASSWORD` environment variables, then the deprecated flags.
With a username and no password, an interactive run prompts for it; a
non-interactive run fails with a message instead of waiting on a terminal.

## The source is untrusted by default

A compromised or malicious AWX could otherwise use the migration against you:

- **Superusers.** A source user flagged `is_superuser`, or holding the
  `system_administrator` / `system_auditor` role, is imported as a normal user
  unless you pass `--grant-superusers`. With it, every promotion is printed and
  recorded in the audit log (`AuditEvent`, `superuser_granted`), even though the
  bulk import disables the activity stream. An import never *removes* superuser
  from a local account.
- **Injectors.** A custom credential type's injectors render into environment
  variables, extra vars and files when a job runs, so a hostile injector is code
  execution on your runners. Without `--trust-injectors`, a new type arrives
  with no injectors; an admin reviews the source's and adds them by editing the
  type. Re-running the import **keeps** those re-approved injectors; if the
  source's differ, that is reported, not applied. Managed (built-in) types are
  matched, never overwritten.

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

## The report

At the end of every run the command prints the counts per resource type and
then **every** warning, grouped in the order to act on them:

1. Privileges GRANTED from the source (only with `--grant-superusers`)
2. Privilege grants SKIPPED
3. Credential-type injectors NOT applied
4. Secrets and passwords to re-enter
5. Role grants Forail rejected
6. Objects skipped

`--report-file PATH` writes the same as JSON (`format: forail-import-report/1`):
the source, the Forail version, the trust options in effect, every object by
name split into `created` and `updated` (names qualified by their organization,
inventory or workflow, where AWX makes them unique), role assignments, secret
fields pending, and the warnings by kind. Run it with `--dry-run` to review a
migration before it touches anything; a report that cannot be written is an
error on stderr, not a failed import.

## Idempotency

Re-running is safe. Objects are matched by natural key — name within
organization (username for users) — and **updated** rather than duplicated. An
`awx_id → Forail object` map is maintained during the run to resolve foreign
keys (e.g. a job template's inventory and project). A re-run's report lists
those objects under `updated`, not `created`.

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
