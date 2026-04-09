# 21 — Observability (OpenTelemetry)

**Tier 3.6 — DONE**

Forge emits **traces** and **metrics** via the OpenTelemetry SDK so operators
can plug it into any OTLP-compatible backend (Grafana Tempo + Prometheus,
Jaeger, Datadog, Honeycomb, New Relic, ...). There is **zero vendor coupling**:
the platform talks only to an OTel Collector, and the Collector fans out.

This feature is additive and fully gated by `OTEL_ENABLED`. When disabled, the
SDK is not even imported, so the overhead is zero.

---

## Architecture

```
              forge-web (Django)            forge-task (Celery)
                   │                               │
                   └──────── OTLP gRPC ────────────┘
                              (4317)
                                │
                                ▼
                      forge-otel-collector
                  (otel/opentelemetry-collector-contrib)
                                │
                   ┌────────────┼────────────┐
                   ▼            ▼            ▼
               Grafana       Jaeger       Datadog  ...
               Tempo /       (traces)     (OTLP)
               Prometheus
```

- Collector config: `forge-deploy/otel/config.yaml`
- Docker Compose service: `forge-otel-collector` in
  `forge-deploy/docker-compose.yml`
- Kubernetes stubs: `forge-deploy/k8s/otel-collector.yaml`,
  `forge-deploy/k8s/grafana-dashboards-cm.yaml` (not yet tested)
- Grafana dashboard: `forge-deploy/grafana/dashboards/forge-overview.json`

## Bootstrap flow

Entry point: `forge.main.observability.init_observability()`.

1. Short-circuits immediately if `OTEL_ENABLED` is false (no SDK import).
2. Lazily imports the OTel SDK + exporter + instrumentation packages.
3. Builds a `Resource` from `OTEL_RESOURCE_ATTRIBUTES` (plus `service.name`).
4. Picks a sampler from `OTEL_TRACES_SAMPLER`
   (`always_on` | `always_off` | `traceidratio` | `parentbased_traceidratio`,
   default `parentbased_traceidratio` with ratio `OTEL_TRACES_SAMPLER_ARG`).
5. Installs a `TracerProvider` with a `BatchSpanProcessor` + OTLP gRPC
   exporter pointed at `OTEL_EXPORTER_ENDPOINT`.
6. Installs a `MeterProvider` with a `PeriodicExportingMetricReader` + OTLP
   metric exporter.
7. Registers auto-instrumentations for Django, Celery, Requests, Psycopg2.
8. All failures are caught and logged — a misconfigured Collector must not
   prevent Django from booting.

Called from `forge/asgi.py`, `forge/wsgi.py`, and the Celery worker boot hook
(`forge/settings/defaults/celery_conf.py`).

## Environment variables / settings registry

All registered in `forge/main/conf.py` under category `System`. Env wins on
first boot; subsequent changes can be made in **Settings → System**.

| Key                        | Default                                   | Meaning                              |
|----------------------------|-------------------------------------------|--------------------------------------|
| `OTEL_ENABLED`             | `false`                                   | Master switch                        |
| `OTEL_EXPORTER_ENDPOINT`   | `http://forge-otel-collector:4317`        | OTLP gRPC endpoint                   |
| `OTEL_SERVICE_NAME`        | `forge`                                   | `service.name` resource attribute    |
| `OTEL_RESOURCE_ATTRIBUTES` | `""`                                      | Comma-separated `k=v` pairs          |
| `OTEL_TRACES_SAMPLER`      | `parentbased_traceidratio`                | Standard OTel sampler names          |
| `OTEL_TRACES_SAMPLER_ARG`  | `0.1`                                     | Ratio in [0,1] (validated)           |

## Span instrumentation seams

Manual root/child spans wrap high-value code paths (see
`forge/main/observability/tracing.py`):

- Launch path in `forge/api/views/job_templates.py`,
  `forge/api/views/workflows.py`, `forge/api/views/ad_hoc_commands.py`:
  root span `forge.launch` with attributes `template_id`, `template_type`,
  `user_id`, `organization_id`, `result`, `gate_blocked`.
- Child span `forge.policy.evaluate` in `forge/main/policy/evaluator.py`.
- Child span `forge.scanner.run` in `forge/main/scanning/runner.py`.

Everything else (HTTP views, DB queries, outgoing requests, Celery tasks)
is covered by the auto-instrumentations.

## Metric handles

Exposed by `forge/main/observability/metrics.py`:

| Metric                             | Type      | Labels                    | Emitted from              |
|------------------------------------|-----------|---------------------------|---------------------------|
| `forge_jobs_launched_total`        | counter   | `status, template_type`   | launch hook               |
| `forge_jobs_blocked_total`         | counter   | `gate` (policy\|scanner)  | launch hook               |
| `forge_job_duration_seconds`       | histogram | —                         | `UnifiedJob` finish hook  |
| `forge_policy_evaluations_total`   | counter   | `decision`                | policy evaluator          |
| `forge_scan_runs_total`            | counter   | `status`                  | scanner runner            |
| `forge_active_jobs`                | gauge     | —                         | Celery beat every 30 s    |

All handles are cheap no-ops when `OTEL_ENABLED=false`.

## REST API

### `GET /api/v2/observability/`

Admin-only. Returns current config plus a best-effort TCP probe against the
Collector endpoint (500 ms timeout, cached for 30 s).

```json
{
  "enabled": true,
  "service_name": "forge",
  "exporter_endpoint": "http://forge-otel-collector:4317",
  "sampler": "parentbased_traceidratio",
  "sampler_arg": "0.1",
  "collector_healthy": true,
  "collector_last_check": "2026-04-09T15:42:00Z"
}
```

## Verification

- `python -m unittest tests_standalone.test_observability -v` — pure helper
  tests (parser / sampler validation / health aggregation).
- E2E smoke via the deployed stack:
  1. `docker compose ps` — `forge-otel-collector` is running.
  2. `curl -sk -u admin:admin https://localhost/api/v2/observability/` —
     returns `enabled: true`, `collector_healthy: true`.
  3. `docker compose logs forge-otel-collector --tail 50` — debug exporter
     prints incoming spans after a job launch.
  4. Settings → System shows the `OTEL_*` keys.
  5. Sidebar → **Observability** shows a green Collector badge.

## Future work

- Point the Collector at a real backend (Tempo / Prometheus / Loki) instead
  of the default `debug` exporter.
- Wire Prometheus alerts back into EDA rules for a closed feedback loop.
- Validate `forge-deploy/k8s/` manifest stubs against a real cluster (see
  `forge-deploy/docs/future_development_plan.md` → *Infrastructure & Test
  Environments*).
