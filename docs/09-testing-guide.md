# 09 — Testing Guide

How to run tests, what to test, and where tests live.

---

## Test Suite Overview

| Suite | Tool | Count | Location |
|-------|------|-------|----------|
| Python unit | pytest | 1083 | `forge/main/tests/unit/` |
| Python functional (API) | pytest | 989 | `forge/main/tests/functional/` |
| Standalone (EDA, drift, service catalog, webauthn, policy, audit) | unittest | 134+ | `tests_standalone/` |
| Frontend | vitest | 72+ | `forge/ui_next/src/**/*.test.{ts,tsx}` |
| Python lint | flake8 | — | `forge/` |
| Frontend lint | TypeScript | — | `forge/ui_next/src/` |

### Standalone Tests (no Django required)

```bash
# Run EDA tests (condition engine, HMAC, throttling, dedup)
python -m unittest tests_standalone.test_eda -v

# Run drift detection tests (compute_drift, hashing, classification, severity)
python -m unittest tests_standalone.test_drift -v

# Run Self-Service Portal lifecycle tests (submit/approve/reject/sync)
python -m unittest tests_standalone.test_service_catalog -v

# Run WebAuthn pure-logic tests (policy resolver, replay guard, helpers)
python -m unittest tests_standalone.test_webauthn -v

# Run Policy-as-Code (OPA) tests (enforcement matrix, fail-mode, parse_decision)
python -m unittest tests_standalone.test_policy -v

# Run all standalone tests
python -m unittest discover tests_standalone -v
```

---

## Running Backend Tests

### Inside Vagrant VM (recommended)

```bash
vagrant ssh
cd /awx_devel

# All unit tests
docker run --rm \
  -v /awx_devel:/awx_devel \
  -e DJANGO_SETTINGS_MODULE=forge.settings.defaults \
  --network docker-compose-prod_forge \
  --user 0 \
  forge-platform/forge:latest \
  bash -c "pip install pytest pytest-django pytest-mock drf-yasg -q && \
    cd /awx_devel && python -m pytest forge/main/tests/unit/ -q"
```

### Useful pytest flags

| Flag | What it does |
|------|-------------|
| `-q` | Quiet output (just pass/fail counts) |
| `-v` | Verbose (show each test name) |
| `-x` | Stop on first failure |
| `-k "pattern"` | Run only tests matching a pattern |
| `--lf` | Run only tests that failed last time |
| `--tb=short` | Short tracebacks |
| `-s` | Show print() output |

### Examples

```bash
# Only tests related to jobs
python -m pytest forge/main/tests/unit/ -k "test_job" -v

# Only one file
python -m pytest forge/main/tests/unit/test_models.py -v

# Stop on first failure with full traceback
python -m pytest forge/main/tests/unit/ -x --tb=long
```

---

## Running Frontend Tests

```bash
cd forge/ui_next
npm ci              # Install dependencies (first time)
npm test            # Run all tests
npm run test:watch  # Watch mode — re-run on changes
```

### Specific file

```bash
npx vitest run src/stores/auth.test.ts
npx vitest run --reporter=verbose
```

---

## Where Tests Live

### Backend

```
forge/main/tests/
├── unit/                       # Pure unit tests (fast, no database)
│   ├── test_models.py
│   ├── test_tasks.py
│   ├── test_access.py          # RBAC permissions
│   ├── test_validators.py
│   └── ...
├── functional/                 # API tests (with database, HTTP requests)
│   ├── test_job_templates.py
│   ├── test_inventories.py
│   ├── test_credentials.py
│   ├── test_rbac.py
│   └── ...
└── conftest.py                 # Shared fixtures
```

### Frontend

Tests live alongside the components they test:

```
src/
├── stores/auth.test.ts         # Test for auth store
├── stores/theme.test.ts        # Test for theme store
├── lib/utils.test.ts           # Test for utility functions
├── lib/statusConfig.test.ts
├── components/
│   ├── ErrorBoundary.test.tsx
│   └── ui/
│       ├── badge.test.tsx
│       └── button.test.tsx
```

---

## What to Test

### When adding a new feature

- **Model:** Validation, computed fields, custom methods
- **API:** CRUD operations, permissions (admin vs regular user vs outsider)
- **Frontend:** Component renders, user can interact, error states

### When fixing a bug

- Write a **regression test** that reproduces the bug before the fix
- The test must fail without the fix and pass with it

### What NOT to test

- Django/DRF internals (already tested)
- Trivial getter/setter methods
- CSS styling

---

## Coverage

### Python

```bash
pip install pytest-cov
python -m pytest forge/main/tests/unit/ \
  --cov=forge \
  --cov-report=term-missing \
  --cov-report=html:htmlcov/
```

### Frontend

```bash
cd forge/ui_next
npx vitest run --coverage
# Output: coverage/index.html
```

---

## Watch Out

1. **Tests use `forge.settings.defaults`**, not production settings.
   If a test passes locally but fails in CI, check if it depends on a
   production-only setting.

2. **Functional tests use a real database.** Each test runs in a transaction
   that is rolled back at the end. But if a test explicitly commits (uses
   `transaction.on_commit`), data may persist — watch for that.

3. **Frontend tests use jsdom** (a simulated browser). If you're testing something
   that depends on the real DOM (scroll, resize, canvas), use Playwright
   or Cypress instead of vitest.

4. **Fixtures in `conftest.py`** — use them for creating test data
   (organization, project, inventory, credentials, templates). Don't repeat
   setup in every test.
