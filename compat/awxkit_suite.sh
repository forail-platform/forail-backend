#!/bin/sh
# awxkit 24.6.1 against a live Forail instance.
#
# Emits one TSV line per check -- PASS/FAIL, name, detail -- and exits
# non-zero if anything failed. Set RUN_JOBS=1 to include the checks that
# actually execute a playbook; they need the task container to be able to
# run podman (FORAIL_TASK_PRIVILEGED=true FORAIL_TASK_CGROUP=host on
# Compose), and are skipped otherwise.
#
# Required: FORAIL_HOST, FORAIL_USER, FORAIL_PASS.
set -u

: "${FORAIL_HOST:?FORAIL_HOST is required (e.g. https://localhost)}"
: "${FORAIL_USER:?FORAIL_USER is required}"
: "${FORAIL_PASS:?FORAIL_PASS is required}"
RUN_JOBS="${RUN_JOBS:-0}"
PUBLIC_PLAYBOOK_REPO="${PUBLIC_PLAYBOOK_REPO:-https://github.com/ansible/ansible-tower-samples.git}"

# --conf.color false: awxkit colours its JSON, which no parser survives.
AWX="awx --conf.host $FORAIL_HOST --conf.username $FORAIL_USER --conf.password $FORAIL_PASS --conf.insecure --conf.color false -f json"

fails=0
pass() { printf 'PASS\t%s\t%s\n' "$1" "${2:-}"; }
fail() { printf 'FAIL\t%s\t%s\n' "$1" "$(printf '%s' "${2:-}" | tr '\n' ' ' | cut -c1-200)"; fails=$((fails + 1)); }
skip() { printf 'SKIP\t%s\t%s\n' "$1" "${2:-}"; }

echo "# awxkit $(awx --version 2>/dev/null) against $FORAIL_HOST"

# ---------------------------------------------------------------- read
for res in ping config me users organizations teams projects project_updates \
           inventory inventory_sources hosts groups credentials credential_types \
           job_templates jobs workflow_job_templates workflow_jobs schedules \
           notification_templates instance_groups instances labels \
           execution_environments applications tokens metrics; do
    case "$res" in
        ping|config|me|metrics) out=$($AWX "$res" 2>&1) ;;
        *)                      out=$($AWX "$res" list --count 1 2>&1) ;;
    esac
    if printf '%s' "$out" | head -c 400 | grep -q '^{'; then
        pass "read $res" "$(printf '%s' "$out" | jq -r '.count // "ok"' 2>/dev/null)"
    else
        fail "read $res" "$out"
    fi
done

out=$($AWX settings list 2>&1)
printf '%s' "$out" | head -c 200 | grep -q '^{' && pass "read settings" "ok" || fail "read settings" "$out"

# ---------------------------------------------------------------- cleanup
# Names are fixed, so a previous run must not collide with this one.
for res in job_templates projects inventory credentials organizations; do
    for id in $($AWX "$res" list --all 2>/dev/null \
                | jq -r '.results[]? | select(.name | startswith("compat-")) | .id' 2>/dev/null); do
        $AWX "$res" delete "$id" >/dev/null 2>&1
    done
done

# ---------------------------------------------------------------- write
ORG=$($AWX organizations create --name compat-org --description "awxkit compatibility suite" 2>&1 | jq -r '.id // empty')
[ -n "$ORG" ] && pass "create organization" "id=$ORG" || { fail "create organization" "no id returned"; echo; echo "cannot continue without an organization"; exit 1; }

INV=$($AWX inventory create --name compat-inv --organization "$ORG" 2>&1 | jq -r '.id // empty')
[ -n "$INV" ] && pass "create inventory" "id=$INV" || fail "create inventory" "no id returned"

HOST=$($AWX hosts create --name compat-host --inventory "$INV" --variables '{"ansible_connection":"local"}' 2>&1 | jq -r '.id // empty')
[ -n "$HOST" ] && pass "create host" "id=$HOST" || fail "create host" "no id returned"

CRED=$($AWX credentials create --name compat-cred --organization "$ORG" --credential_type 1 --inputs '{"username":"demo"}' 2>&1 | jq -r '.id // empty')
[ -n "$CRED" ] && pass "create credential" "id=$CRED" || fail "create credential" "no id returned"

MOD=$($AWX organizations modify "$ORG" --description "modified by the suite" 2>&1)
printf '%s' "$MOD" | jq -e '.description == "modified by the suite"' >/dev/null 2>&1 \
    && pass "modify organization" "ok" || fail "modify organization" "$MOD"

GET=$($AWX organizations get "$ORG" 2>&1)
printf '%s' "$GET" | jq -e '.id' >/dev/null 2>&1 && pass "get organization" "ok" || fail "get organization" "$GET"

# ---------------------------------------------------------------- export / import
EXPORT=$($AWX export 2>/dev/null)
if printf '%s' "$EXPORT" | jq -e 'has("organizations") and has("job_templates")' >/dev/null 2>&1; then
    pass "export" "$(printf '%s' "$EXPORT" | jq -r 'to_entries | map(.value | length) | add') objects"
else
    fail "export" "unexpected payload"
fi

# Importing an export back into the instance it came from must be a no-op.
# `users` is expected to be rejected: export never carries passwords, so the
# user POST is refused with "password: This field may not be blank" -- the
# same on AWX. Everything else has to come back clean.
IMPORT=$(printf '%s' "$EXPORT" | $AWX import 2>&1)
if printf '%s' "$IMPORT" | grep -v '/api/v2/users/' | grep -q 'Bad Request\|Traceback'; then
    fail "import (round-trip)" "$IMPORT"
else
    pass "import (round-trip)" "idempotent"
fi

# ---------------------------------------------------------------- execution
if [ "$RUN_JOBS" != "1" ]; then
    skip "project sync (git)"     "RUN_JOBS=1 to enable"
    skip "create job template"    "RUN_JOBS=1 to enable"
    skip "launch job"             "RUN_JOBS=1 to enable"
    echo
    echo "$fails failed"
    [ "$fails" -eq 0 ]
    exit $?
fi

PRJ=$($AWX projects create --name compat-prj --organization "$ORG" --scm_type git \
        --scm_url "$PUBLIC_PLAYBOOK_REPO" --wait 2>&1 | jq -r '.id // empty')
if [ -n "$PRJ" ]; then
    # `--wait` returns before the record is refreshed, so ask the API whether
    # the sync actually produced playbooks rather than trusting the status.
    PLAYBOOKS=$(curl -sk -u "$FORAIL_USER:$FORAIL_PASS" "$FORAIL_HOST/api/v2/projects/$PRJ/playbooks/")
    if printf '%s' "$PLAYBOOKS" | jq -e 'length > 0' >/dev/null 2>&1; then
        pass "project sync (git)" "$(printf '%s' "$PLAYBOOKS" | jq -r 'join(",")')"
    else
        fail "project sync (git)" "no playbooks after sync -- see /api/v2/projects/$PRJ/project_updates/"
    fi
else
    fail "project sync (git)" "project not created"
fi

JT=$($AWX job_templates create --name compat-jt --project "$PRJ" --inventory "$INV" --playbook hello_world.yml 2>&1 | jq -r '.id // empty')
[ -n "$JT" ] && pass "create job template" "id=$JT" || fail "create job template" "not created"

if [ -n "$JT" ]; then
    JOB=$($AWX job_templates launch "$JT" --wait 2>&1)
    JOBID=$(printf '%s' "$JOB" | jq -r '.id // empty')
    STATUS=$(curl -sk -u "$FORAIL_USER:$FORAIL_PASS" "$FORAIL_HOST/api/v2/jobs/$JOBID/" | jq -r '.status')
    [ "$STATUS" = "successful" ] && pass "launch job" "job $JOBID successful" \
                                 || fail "launch job" "job $JOBID status=$STATUS"
fi

echo
echo "$fails failed"
[ "$fails" -eq 0 ]
