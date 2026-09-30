#!/usr/bin/env bash
# Run the Django functional tests from this checkout inside a published
# backend image.
#
# The functional tests need the whole application importable -- python-ldap,
# xmlsec, receptorctl and the rest -- which is slow and fragile to install on
# a runner or a laptop. The published image already has all of it, so copy
# this checkout's `forail` package over the image's and run pytest there.
# The image only supplies dependencies: every line of Forail code under test
# comes from the working tree.
#
#   tools/scripts/functional-tests-in-image.sh                # whole suite
#   tools/scripts/functional-tests-in-image.sh forail/sso/tests/functional -k saml
#
# FORAIL_TEST_IMAGE  image to borrow dependencies from (default below). Bump
#                    it when requirements/ change, or the run tests new code
#                    against old libraries.
# KNOWN_FAILURES     file of test ids to deselect (default: the CI list;
#                    set it to /dev/null to run everything).
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
IMAGE=${FORAIL_TEST_IMAGE:-ghcr.io/forail-platform/forail-backend:2026.07.2-rc1}
KNOWN=${KNOWN_FAILURES:-$ROOT/.github/functional-known-failures.txt}

if [ $# -eq 0 ]; then
  set -- forail/main/tests/functional forail/sso/tests/functional
fi

deselect=()
while IFS= read -r line; do
  case "$line" in ''|'#'*) continue ;; esac
  deselect+=("--deselect=$line")
done < "$KNOWN"

# test_ldap and test_migrations import mockldap / django_test_migrations,
# which are not in the runtime image and not worth pulling in for them.
exec docker run --rm --user root \
  -v "$ROOT/forail:/tmp/src/forail:ro" \
  -w /tmp --entrypoint bash "$IMAGE" -c '
    set -euo pipefail
    SP=$(ls -d /var/lib/awx/venv/awx/lib/python3.*/site-packages)
    rm -rf "$SP/forail"
    cp -r /tmp/src/forail "$SP/forail"
    # pytest-asyncio is deliberately absent: it needs a newer
    # typing_extensions than the application pins, and nothing here is async.
    pip install -q --break-system-packages \
      pytest pytest-django pytest-mock pytest-xdist drf-yasg logutils colorama django-debug-toolbar >/dev/null
    cd "$SP"
    exec python3 -m pytest -p no:cacheprovider -p no:asyncio -n auto \
      -o addopts="--nomigrations --tb=short -q" \
      -o DJANGO_SETTINGS_MODULE=forail.main.tests.settings_for_test \
      --ignore=forail/main/tests/functional/test_ldap.py \
      --ignore=forail/main/tests/functional/test_migrations.py \
      "$@"
  ' _ "${deselect[@]}" "$@"
