# 21 — Observability (OpenTelemetry)

**Tier 3.6 — DONE**

Forail emits **traces** and **metrics** via the OpenTelemetry SDK so operators
can plug it into any OTLP-compatible backend (Grafana Tempo + Prometheus,
Jaeger, Datadog, Honeycomb, New Relic, ...). There is **zero vendor coupling**:
the platform talks only to an OTel Collector, and the Collector fans out.

This feature is additive and fully gated by `OTEL_ENABLED`. When disabled, the
SDK is not even imported, so the overhead is zero.

---

## Architecture

```
              forail-web (Django)            forail-task (Celery)
                   │                               │
                   └──────── OTLP gRPC ────────────┘
                              (4317)
                                │
                                ▼
                      forail-otel-collector
                  (otel/opentelemetry-collector-contrib)
                                │
                   ┌────────────┼────────────┐
                   ▼            ▼            ▼
               Grafana       Jaeger       Datadog  ...
               Tempo /       (traces)     (OTLP)
               Prometheus
```

- Collector config: `forail-deploy/otel/config.yaml`
- Docker Compose service: `forail-otel-collector` in
  `forail-deploy/docker-compose.yml`
- Kubernetes stubs: `forail-deploy/k8s/otel-collector.yaml`,
  `forail-deploy/k8s/grafana-dashboards-cm.yaml` (not yet tested)
- Grafana dashboard: `forail-deploy/grafana/dashboards/forail-overview.json`

## Bootstrap flow

Entry point: `forail.main.observability.init_observability()`.

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

Called from `forail/asgi.py`, `forail/wsgi.py`, and the Celery worker boot hook
(`forail/settings/defaults/celery_conf.py`).

## Environment variables / settings registry

All registered in `forail/main/conf.py` under category `System`. Env wins on
first boot; subsequent changes can be made in **Settings → System**.

| Key                        | Default                            | Meaning                           |
| -------------------------- | ---------------------------------- | --------------------------------- |
| `OTEL_ENABLED`             | `false`                            | Master switch                     |
| `OTEL_EXPORTER_ENDPOINT`   | `http://forail-otel-collector:4317` | OTLP gRPC endpoint                |
| `OTEL_SERVICE_NAME`        | `forail`                            | `service.name` resource attribute |
| `OTEL_RESOURCE_ATTRIBUTES` | `""`                               | Comma-separated `k=v` pairs       |
| `OTEL_TRACES_SAMPLER`      | `parentbased_traceidratio`         | Standard OTel sampler names       |
| `OTEL_TRACES_SAMPLER_ARG`  | `0.1`                              | Ratio in [0,1] (validated)        |

## Span instrumentation seams

Manual root/child spans wrap high-value code paths (see
`forail/main/observability/tracing.py`):

- Launch path in `forail/api/views/job_templates.py`,
  `forail/api/views/workflows.py`, `forail/api/views/ad_hoc_commands.py`:
  root span `forail.launch` with attributes `template_id`, `template_type`,
  `user_id`, `organization_id`, `result`, `gate_blocked`.
- Child span `forail.policy.evaluate` in `forail/main/policy/evaluator.py`.
- Child span `forail.scanner.run` in `forail/main/scanning/runner.py`.

Everything else (HTTP views, DB queries, outgoing requests, Celery tasks)
is covered by the auto-instrumentations.

## Metric handles

Exposed by `forail/main/observability/metrics.py`:

| Metric                           | Type      | Labels                   | Emitted from             |
| -------------------------------- | --------- | ------------------------ | ------------------------ |
| `forail_jobs_launched_total`      | counter   | `status, template_type`  | launch hook              |
| `forail_jobs_blocked_total`       | counter   | `gate` (policy\|scanner) | launch hook              |
| `forail_job_duration_seconds`     | histogram | —                        | `UnifiedJob` finish hook |
| `forail_policy_evaluations_total` | counter   | `decision`               | policy evaluator         |
| `forail_scan_runs_total`          | counter   | `status`                 | scanner runner           |
| `forail_active_jobs`              | gauge     | —                        | Celery beat every 30 s   |

All handles are cheap no-ops when `OTEL_ENABLED=false`.

## REST API

### `GET /api/v2/observability/`

Admin-only. Returns current config plus a best-effort TCP probe against the
Collector endpoint (500 ms timeout, cached for 30 s).

```json
{
  "enabled": true,
  "service_name": "forail",
  "exporter_endpoint": "http://forail-otel-collector:4317",
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
  1. `docker compose ps` — `forail-otel-collector` is running.
  2. `curl -sk -u admin:admin https://localhost/api/v2/observability/` —
     returns `enabled: true`, `collector_healthy: true`.
  3. `docker compose logs forail-otel-collector --tail 50` — debug exporter
     prints incoming spans after a job launch.
  4. Settings → System shows the `OTEL_*` keys.
  5. Sidebar → **Observability** shows a green Collector badge.

## Future work

- Point the Collector at a real backend (Tempo / Prometheus / Loki) instead
  of the default `debug` exporter.
- Wire Prometheus alerts back into EDA rules for a closed feedback loop.
- Validate `forail-deploy/k8s/` manifest stubs against a real cluster (see
  `forail-deploy/docs/future_development_plan.md` → _Infrastructure & Test
  Environments_).
