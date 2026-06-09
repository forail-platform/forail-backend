# 20 — IaC Scanning & Supply Chain Security

Content-level static analysis of playbooks and Python requirements at
launch time. Where Policy-as-Code (doc 19) reasons about **metadata**
(who is launching what against which inventory), the scanner reasons
about what is **inside** the playbook: `shell:` with unquoted variables,
unpinned role sources, hard-coded secrets, Python dependencies with
known CVEs.

Three open-source CLIs run as subprocesses out of the forail venv:

- **ansible-lint** — Ansible rules catalog (MIT)
- **checkov** — multi-IaC scanner incl. Ansible (Apache 2.0)
- **pip-audit** — Python CVEs via OSV (Apache 2.0, PyPA)

The hook fires on `JobTemplateLaunch`, `WorkflowJobTemplateLaunch` and
`AdHocCommandList.create`, **after** the Policy-as-Code hook so policy
denials short-circuit before we spend CPU on a scan.

---

## Architecture

```
  Launch view                                      Scanner model rows
  ───────────                                      ──────────────────
  create_unified_job()
         │
         ▼
  evaluate_launch()   ← policy (doc 19)
         │
         ▼
  run_scanners_for_launch(unified_job, request)
         │
         │  For each Scanner enabled & applies_to match:
         │    resolve project_path + target (playbook/requirements)
         │    subprocess.run(cmd, timeout=SCANNER_TIMEOUT_S)
         │    adapter.parse_output → list[NormalizedFinding]
         │    filter by severity_threshold
         │    persist ScanResult + N ScanFinding rows
         ▼
  ScanRunResult(allowed, warn_messages, block_messages, results)
         │
    ┌────┴────┐
    ▼         ▼
  allowed   blocked → delete UJ, 403 with reasons
    │
  warn → append one-liner to job_explanation, signal_start
```

When `SCANNER_ENABLED=False`, `run_scanners_for_launch` returns an
empty allow-immediately `ScanRunResult`.

---

## Models — `forail/main/models/scanner.py`

### `Scanner(CommonModelNameNotUnique)`

| Field                                             | Notes                                                                              |
| ------------------------------------------------- | ---------------------------------------------------------------------------------- |
| `organization`                                    | FK Organization (null = global)                                                    |
| `description`                                     | TextField                                                                          |
| `tool`                                            | `ansible-lint` / `checkov` / `pip-audit`                                           |
| `config`                                          | JSONField — adapter-specific opts (excludes, profile, etc.)                        |
| `severity_threshold`                              | `info` / `low` / `medium` / `high` / `critical`                                    |
| `enforcement`                                     | `warn` / `enforce`                                                                 |
| `enabled`                                         | bool                                                                               |
| `applies_to`                                      | JSON list: `job_template`, `workflow_job_template`, `ad_hoc_command` (empty = all) |
| `trigger_count`, `last_run_at`, `last_run_status` | populated by the runner                                                            |

### `ScanResult(CreatedModifiedModel)`

One row per scanner execution.

| Field                  | Notes                                                         |
| ---------------------- | ------------------------------------------------------------- |
| `scanner`              | FK Scanner (SET_NULL)                                         |
| `scanner_name`         | Cached name so historical rows survive delete                 |
| `unified_job`          | FK UnifiedJob (SET_NULL) — nulled when the launch was blocked |
| `unified_job_template` | FK UnifiedJobTemplate (SET_NULL)                              |
| `organization`         | FK Organization (SET_NULL)                                    |
| `triggered_by`         | FK auth.User (SET_NULL)                                       |
| `status`               | `ok` / `warn` / `blocked` / `error` / `timeout`               |
| `duration_ms`          | Wall-clock scanner runtime                                    |
| `finding_count`        | Findings at or above threshold                                |
| `highest_severity`     | Cached for filtering / audit UI                               |
| `message`              | Short summary (first finding)                                 |
| `raw_output`           | Truncated stdout/stderr (`SCANNER_RAW_OUTPUT_MAX` bytes)      |

### `ScanFinding(BaseModel)`

| Field         | Notes                                                       |
| ------------- | ----------------------------------------------------------- |
| `scan_result` | FK ScanResult CASCADE                                       |
| `rule_id`     | e.g. `yaml[line-length]`, `CKV_ANSIBLE_*`, PyPI advisory id |
| `severity`    | Normalized to `info/low/medium/high/critical`               |
| `file_path`   | Relative to project checkout                                |
| `line`        | Optional                                                    |
| `message`     | Human-readable                                              |

Migration: `forail/main/migrations/0203_scanner.py`. All three models are
registered with `permission_registry` and `activity_stream_registrar`.

### Pure helpers

Exported from the model module and unit-tested without Django bootstrap:

```python
severity_at_or_above(finding_sev, threshold) -> bool
effective_enforcement(global_enabled, scanner_enforcement) -> str
aggregate_status(findings, threshold) -> 'ok' | 'warn' | 'blocked'
fail_mode_decision(scanner_unavailable, fail_mode) -> 'allow' | 'deny'
```

Severity ordering: `info(0) < low(1) < medium(2) < high(3) < critical(4)`.

---

## Tool adapters — `forail/main/scanning/tools/`

One file per tool. Each exposes the same interface used by the runner:

```python
build_command(target_path, config) -> list[str]
parse_output(stdout, stderr, returncode) -> list[NormalizedFinding]
```

`NormalizedFinding` (from `forail.main.scanning.types`) has
`rule_id, severity, file_path, line, message`.

| Adapter           | CLI invocation                                      | Severity mapping                                                                                                          |
| ----------------- | --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `ansible_lint.py` | `ansible-lint -f json --strict <playbook>`          | Rule tag → info/low/medium/high/critical. `very_high`/`security` → high; `med`/`medium` → medium; `info`/`notice` → info. |
| `checkov.py`      | `checkov -f <playbook> --framework ansible -o json` | `CRITICAL`→critical, `HIGH`→high, `MEDIUM`→medium, `LOW`→low; anything else → info.                                       |
| `pip_audit.py`    | `pip-audit -r <requirements.txt> --format json`     | OSV severity field → mapped directly; missing → medium by default.                                                        |

A tool registry in `forail/main/scanning/tools/__init__.py` exposes
`get_adapter(tool_name)` used by the runner.

---

## Runner — `forail/main/scanning/runner.py`

```python
def run_scanners_for_launch(unified_job, request=None) -> ScanRunResult:
```

`ScanRunResult`:

```python
@dataclass
class ScanRunResult:
    allowed: bool = True
    warn_messages: list[str] = []
    block_messages: list[str] = []
    results: list[ScanResult] = []
```

Resolution rules:

- **`job_template`** → target is `<project_path>/<playbook>`. `ansible-lint`
  and `checkov` scan the playbook file; `pip-audit` scans the project
  root (expects a `requirements.txt`).
- **`workflow_job_template`** → skipped (no single playbook).
- **`ad_hoc_command`** → target is the project path (if any);
  `ansible-lint` is skipped.

Per-scanner execution:

1. Pick adapter, build command.
2. `subprocess.run(..., timeout=SCANNER_TIMEOUT_S, capture_output=True)`.
3. On `TimeoutExpired` → status `timeout`; on `FileNotFoundError` or
   other `OSError` → status `error`. Both go through
   `fail_mode_decision(unavailable=True, SCANNER_FAIL_MODE)` to decide
   whether to block or warn.
4. Otherwise parse output, filter by the scanner's `severity_threshold`,
   compute highest severity and aggregated status.
5. Persist `ScanResult` + `ScanFinding` rows.
6. Update `last_run_at`, `last_run_status`, optionally `trigger_count`.
7. Append to `warn_messages` or `block_messages`.

When a scanner blocks, `ScanResult.unified_job` is set to `NULL` so
the FK cascade doesn't lose the audit row when the view deletes the job.

---

## Settings — `forail/main/conf.py`

Registered under the **Security** category:

| Setting                  | Default | Notes                                                                                                                      |
| ------------------------ | ------- | -------------------------------------------------------------------------------------------------------------------------- |
| `SCANNER_ENABLED`        | `False` | Master switch; runner is a no-op otherwise.                                                                                |
| `SCANNER_TIMEOUT_S`      | `120`   | Per-scanner subprocess timeout in seconds.                                                                                 |
| `SCANNER_FAIL_MODE`      | `allow` | What to do when a scanner crashes/times out. `allow` = fail-open (warn row logged), `deny` = fail-closed (launch blocked). |
| `SCANNER_RAW_OUTPUT_MAX` | `8192`  | Bytes of tool stdout/stderr kept on each `ScanResult.raw_output`.                                                          |

---

## View hooks

Same three launch views as Policy-as-Code, inserted **after** the OPA
hook so a policy denial short-circuits the scan:

- `forail/api/views/job_templates.py` → `JobTemplateLaunch.post`
- `forail/api/views/workflows.py` → `WorkflowJobTemplateLaunch.post`
- `forail/api/views/ad_hoc_commands.py` → `AdHocCommandList.create`

```python
from forail.main.scanning.runner import run_scanners_for_launch
scan_result = run_scanners_for_launch(new_job, request)
if not scan_result.allowed:
    new_job.delete()
    return Response(
        {'detail': 'Scanner blocked launch.',
         'reasons': scan_result.block_messages},
        status=403,
    )
if scan_result.warn_messages:
    existing = new_job.job_explanation or ''
    new_job.job_explanation = (
        existing + '\nScan warnings: ' +
        '; '.join(scan_result.warn_messages)
    )[:1024]
    new_job.save(update_fields=['job_explanation'])
```

---

## REST API

Mounted under `/api/v2/scanners/` and `/api/v2/scan_results/`.

| Method               | Path                             | Purpose                                                    |
| -------------------- | -------------------------------- | ---------------------------------------------------------- |
| GET / POST           | `/api/v2/scanners/`              | List + create                                              |
| GET / PATCH / DELETE | `/api/v2/scanners/{id}/`         | CRUD                                                       |
| POST                 | `/api/v2/scanners/{id}/enable/`  | Enable                                                     |
| POST                 | `/api/v2/scanners/{id}/disable/` | Disable                                                    |
| GET                  | `/api/v2/scan_results/`          | List (filter: `scanner`, `status`, `unified_job`, `since`) |
| GET                  | `/api/v2/scan_results/{id}/`     | Detail with embedded findings                              |

---

## Tests — `tests_standalone/test_scanner.py`

Standalone unit tests, no Django bootstrap (same pattern as
`test_policy.py` and `test_drift.py`):

- `severity_at_or_above` matrix — info < low < medium < high < critical.
- `effective_enforcement` matrix (global_enabled × scanner_enforcement).
- `aggregate_status` — no findings → `ok`; below threshold → `ok`;
  at/above + warn → `warn`; at/above + enforce → `blocked`.
- `fail_mode_decision` — (unavailable, `allow`) → `allow`;
  (unavailable, `deny`) → `deny`; (available, \*) → `allow`.
- Adapter parsers fed canned JSON fixtures (ansible-lint, checkov,
  pip-audit) → expected NormalizedFinding lists.
- `applies_to` resource matching (empty list = all; subset match).

Run with: `python -m unittest tests_standalone.test_scanner -v`

---

## Deployment

- The scanner CLIs live inside the `forail-backend` image, installed
  into `/var/lib/awx/venv/awx` so Django subprocess calls find them
  on PATH. See `forail-backend/Dockerfile`:

  ```dockerfile
  RUN /var/lib/awx/venv/awx/bin/pip install --no-cache-dir \
          'ansible-lint==25.1.*' \
          'checkov==3.2.*' \
          'pip-audit==2.7.*'
  ```

- No new compose service is needed. The `forail_projects` named volume
  is already mounted on all forail containers (via the `x-forail-common`
  anchor in `docker-compose.yml`), so the runner sees the project
  checkout path on disk.

---

## End-to-end manual verification

1. Settings → Security → set `SCANNER_ENABLED=true`.
2. Create a Scanner: name `block-shell-injection`, tool `ansible-lint`,
   `severity_threshold=high`, `enforcement=enforce`,
   `applies_to=[job_template]`.
3. Create a project with a playbook that violates a high-severity
   ansible-lint rule (e.g. `shell:` with an unquoted Jinja variable).
4. Launch that JT → 403 with the rule_id in `reasons`; a `ScanResult`
   row appears with `status=blocked`.
5. Lower `severity_threshold` to `critical` (rule is `high`) → launch
   succeeds, `ScanResult.status=ok`, `job_explanation` unchanged.
6. Set `enforcement=warn`, threshold back to `high` → launch succeeds
   but `job_explanation` shows the one-line warning summary.
7. Disable the scanner → launch is silent, no new `ScanResult` row.
8. Set `SCANNER_TIMEOUT_S=1`, point at a very large playbook →
   `ScanResult.status=timeout`, behavior follows `SCANNER_FAIL_MODE`
   (`allow` = warn, `deny` = blocked).
