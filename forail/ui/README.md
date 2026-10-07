# forail.ui

What is left of the upstream AWX UI app, and why it stays.

**The Forail UI is not here.** It is
[forail-frontend](https://github.com/forail-platform/forail-frontend), built
and shipped as its own image and routed at the site root by nginx or the
Helm ingress. The backend image is headless and serves the API only.

## What this app still does

| File | Why it is live |
|---|---|
| `conf.py`, `fields.py` | Register `CUSTOM_LOGO`, `CUSTOM_LOGIN_INFO`, `PENDO_TRACKING_STATE` and the other `ui` settings category. `/api/v2/settings/ui/` and `/api/v2/config/` expose them, and AWX clients (`awxkit`, `awx.awx`) read them |
| `context_processors.py` | `csp_nonce` and `version` for every Django template, including the browsable API |
| `urls.py` | `/ui_legacy/migrations_notran/` — the page the migration middleware sends requests to while the database is being migrated. `/ui_legacy/` itself only redirects to `/` |
| `public/installing.html` | That page's template. Self-contained on purpose: during an upgrade the collected static files may still belong to the previous version |

## What was removed (2026-09)

The upstream PatternFly React app (`src/`, `testUtils/`, npm config — about
16 MB and 1,650 files) and the `forail.ui_next` catch-all. Nothing built the
former; the latter rendered a template that was on no template path and
returned 500 for every non-API URL that reached the backend directly.
