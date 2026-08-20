# AWX API compatibility

AWX has had no release since **24.6.1, 2 July 2024**. The clients that
users of it already have — the `awx` CLI (`awxkit`) and the `awx.awx`
Ansible collection — are therefore frozen at that version, and whatever
they have automated is written against it.

This directory answers one question with a suite you can re-run rather
than a claim: **do those clients, unmodified, work against Forail?**

## What was measured

Against a single-node Compose install of `2026.07.2-rc1`, with
`awxkit==24.6.1` and `awx.awx:24.6.1` installed from PyPI and Galaxy —
no Forail-specific patches, plugins, or wrappers on the client side.

### `awx` CLI (awxkit 24.6.1) — 38 checks, 0 failed

| Area | Checks | Result |
|---|---|---|
| Read every top-level resource | `ping`, `config`, `me`, `metrics`, `settings`, `users`, `organizations`, `teams`, `projects`, `project_updates`, `inventory`, `inventory_sources`, `hosts`, `groups`, `credentials`, `credential_types`, `job_templates`, `jobs`, `workflow_job_templates`, `workflow_jobs`, `schedules`, `notification_templates`, `instance_groups`, `instances`, `labels`, `execution_environments`, `applications`, `tokens` | 28/28 pass |
| Create | organization, inventory, host, credential | 4/4 pass |
| Modify / get | organization | 2/2 pass |
| `awx export` | 14 object types in one payload | pass |
| `awx import` | round-trip back into the same instance | pass, idempotent |
| Project sync from git | public git repo → playbooks discovered | pass |
| Job template + `launch --wait` | `hello_world.yml` | pass, `successful` |

### `awx.awx` collection 24.6.1 — 11 checks, 0 failed

| Module / plugin | Result |
|---|---|
| `controller_meta` | pass |
| `organization` | pass |
| `organization` re-run | pass — `changed=false`, so idempotency holds |
| `inventory` | pass |
| `host` | pass |
| `credential` | pass |
| `project` | pass |
| `controller_api` lookup plugin | pass |
| `export` | pass |
| `project_update` (wait) | pass, `successful` |
| `job_template` | pass |
| `job_launch` (wait) | pass, `successful` |

## Compatibility statement

An existing AWX 24.6.1 client talks to Forail without modification. In
practice that means an `awx.awx` playbook or an `awx` CLI script written
against AWX runs against Forail by changing the host it points at — the
resource names, the request and response shapes, and the semantics the
collection depends on (including idempotency) are the same, and
`export`/`import` work in both directions.

Two caveats, both honest:

- **This covers the surface the suite exercises**, listed above. It is
  the surface ordinary automation uses, not every endpoint AWX has.
  Notably untested here: workflows, schedules as a write path,
  notifications, RBAC edge cases, and custom credential types.
- **The failures we did hit were awxkit's own**, not Forail's. `awxkit
  24.6.1` will not start on a current Python: it imports `pkg_resources`
  (removed in setuptools 81) and calls a private `argparse` API whose
  signature changed in later 3.12 patch releases. The suite pins around
  both. A user on a modern distro has to do the same to run `awx` at all
  — against AWX itself included.

## Running it

Needs a live Forail instance and Docker.

```bash
docker build -t forail-compat compat/

# API surface only -- no playbook is executed
docker run --rm --network host \
  -e FORAIL_HOST=https://localhost \
  -e FORAIL_USER=admin \
  -e FORAIL_PASS=... \
  forail-compat sh awxkit_suite.sh

docker run --rm --network host \
  -e FORAIL_HOST=https://localhost -e FORAIL_USER=admin -e FORAIL_PASS=... \
  forail-compat ansible-playbook collection_suite.yml
```

Add `-e RUN_JOBS=1` to include project sync and job execution. Those need
the task container to be able to run podman, which on Compose means
bringing the stack up with:

```bash
FORAIL_TASK_PRIVILEGED=true FORAIL_TASK_CGROUP=host docker compose up -d
```

That is off by default because a privileged container is a trivial escape
to host root; see H4 in the security notes.

Both suites exit non-zero if any check fails, and both create objects
named `compat-*` / `coll-*`, cleaning up their own leftovers on the next
run.

## Version note

Do not run this against `2026.07.0`. On that image the node registers as
`control` regardless of what is asked for, and the `default` queue is a
Kubernetes container group — so on Compose project updates fail with
`unknown work type kubernetes-incluster-auth` and every job stays
`pending`. Fixed by 0cb32fe; `2026.07.2-rc1` is the lowest published tag
that carries it for both the backend and the frontend image.
