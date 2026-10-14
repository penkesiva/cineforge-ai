#!/usr/bin/env bash
# Self-test for scripts/demo_live.sh with a fake `curl` on PATH (no network, no stack).
# Usage: scripts/tests/test_demo_live.sh   (or `make test-scripts`)
set -euo pipefail

SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/demo_live.sh"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

passed=0
failed=0

mkdir -p "$WORK/bin"
cat >"$WORK/bin/curl" <<'EOF'
#!/usr/bin/env bash
# Fake curl: answers the CineForge API calls demo_live.sh makes; logs every call.
method=GET
url=""
while [ $# -gt 0 ]; do
  case "$1" in
    -X) method="$2"; shift ;;
    -d) printf '%s\n' "$2" >>"$FAKE_LOG.body"; shift ;;
    -H) shift ;;
    http*) url="$1" ;;
  esac
  shift
done
echo "$method $url" >>"$FAKE_LOG"
path="${url#*://*/}"
case "$method /$path" in
  "GET /api/v1/providers")
    [ "${FAKE_PROVIDERS:-ok}" = "down" ] && exit 22
    echo "{\"provider_mode\":\"${FAKE_STACK_MODE:-live}\",\"paid_providers_allowed\":${FAKE_STACK_PAID:-true},\"secrets_backend\":\"vault\",\"groups\":[{\"capability\":\"llm_text\",\"label\":\"LLM\",\"providers\":[],\"active_provider\":\"anthropic\"}]}" ;;
  "POST /api/v1/productions")
    echo '{"summary":{"id":"prod_fake","state":"DRAFT"}}' ;;
  "POST /api/v1/productions/prod_fake/run")
    echo '{"production_id":"prod_fake","state":"RESEARCHING","message":"ok","job_id":"job_1"}' ;;
  "GET /api/v1/productions/prod_fake")
    cat <<JSON
{"summary":{"id":"prod_fake","state":"${FAKE_FINAL_STATE:-AWAITING_APPROVAL}"},
 "artifacts":{
  "research":{"claims":[{"id":"claim_1","status":"verified"},{"id":"claim_2","status":"verified"},{"id":"claim_3","status":"unverified"}]},
  "media":{"candidates":[
    {"candidate_id":"c1","provider":"wikimedia_commons","rights_status":"approved"},
    {"candidate_id":"c2","provider":"openverse","rights_status":"approved"},
    {"candidate_id":"c3","provider":"openverse","rights_status":"blocked"}],
   "selected_ids":["c1","c2"],"blocked":{"c3":"license unknown"}}}}
JSON
    ;;
  "GET /api/v1/productions/prod_fake/costs")
    echo '{"production_id":"prod_fake","currency":"USD","limit":1.0,"actual":0.0421,"reserved":0.0,"remaining":0.9579,"by_provider":[{"key":"anthropic","label":"anthropic","actual":0.0421,"event_count":4}],"simulated":false}' ;;
  *)
    echo "fake curl: unexpected $method $url" >&2
    exit 22 ;;
esac
EOF
chmod +x "$WORK/bin/curl"

# run_case <expect pass|fail> <description> <stdin answer> [ENV=VALUE...]
# Runs with a clean provider environment and an empty .env unless ENV_FILE is given.
run_case() {
  local want="$1" desc="$2" answer="$3"
  shift 3
  : >"$WORK/calls.log"
  : >"$WORK/calls.log.body"
  : >"$WORK/empty.env"
  local got
  if printf '%s\n' "$answer" | env -u PROVIDER_MODE -u ALLOW_PAID_PROVIDERS -u DEMO_BUDGET_USD \
    PATH="$WORK/bin:$PATH" FAKE_LOG="$WORK/calls.log" ENV_FILE="$WORK/empty.env" \
    API_URL=http://api.test DEMO_POLL_SEC=0 "$@" bash "$SCRIPT" >"$WORK/out.log" 2>&1; then
    got=pass
  else
    got=fail
  fi
  if [ "$got" = "$want" ]; then
    passed=$((passed + 1))
    echo "ok   - $desc"
  else
    failed=$((failed + 1))
    echo "FAIL - $desc (expected $want, got $got)"
    sed 's/^/       /' "$WORK/out.log"
  fi
}

# assert <description> <command...>
assert() {
  local desc="$1"
  shift
  if "$@"; then
    passed=$((passed + 1))
    echo "ok   - $desc"
  else
    failed=$((failed + 1))
    echo "FAIL - $desc"
    sed 's/^/       /' "$WORK/out.log"
  fi
}

no_post() { ! grep -q '^POST' "$WORK/calls.log"; }
no_calls() { [ ! -s "$WORK/calls.log" ]; }
out_has() { grep -qF -- "$1" "$WORK/out.log"; }

run_case fail "refuses with no settings (defaults mock + paid off)" spend
assert "  ...and makes no API calls" no_calls

run_case fail "refuses PROVIDER_MODE=mock" spend PROVIDER_MODE=mock ALLOW_PAID_PROVIDERS=true
assert "  ...and makes no API calls" no_calls

run_case fail "refuses live mode with ALLOW_PAID_PROVIDERS=false" spend \
  PROVIDER_MODE=live ALLOW_PAID_PROVIDERS=false
assert "  ...and makes no API calls" no_calls

cat >"$WORK/live.env" <<'EOF'
# live settings
PROVIDER_MODE=live   # comment
export ALLOW_PAID_PROVIDERS="true"
DEMO_BUDGET_USD=0.50
EOF
run_case pass "reads PROVIDER_MODE / ALLOW_PAID_PROVIDERS / DEMO_BUDGET_USD from .env" spend \
  ENV_FILE="$WORK/live.env"
assert "  ...prints the budget cap from .env" out_has "budget cap       USD 0.50"

run_case fail "environment wins over .env" spend ENV_FILE="$WORK/live.env" PROVIDER_MODE=mock
assert "  ...and makes no API calls" no_calls

run_case fail "rejects a non-numeric DEMO_BUDGET_USD" spend \
  PROVIDER_MODE=live ALLOW_PAID_PROVIDERS=true DEMO_BUDGET_USD=lots
run_case fail "rejects a zero DEMO_BUDGET_USD" spend \
  PROVIDER_MODE=live ALLOW_PAID_PROVIDERS=true DEMO_BUDGET_USD=0.00

run_case fail "aborts unless the operator types 'spend'" yes \
  PROVIDER_MODE=live ALLOW_PAID_PROVIDERS=true
assert "  ...and creates nothing" no_post

run_case fail "aborts on empty stdin" "" PROVIDER_MODE=live ALLOW_PAID_PROVIDERS=true
assert "  ...and creates nothing" no_post

run_case fail "refuses when the running stack is still in mock mode" spend \
  PROVIDER_MODE=live ALLOW_PAID_PROVIDERS=true FAKE_STACK_MODE=mock
assert "  ...and creates nothing" no_post

run_case fail "refuses when the running stack has paid providers off" spend \
  PROVIDER_MODE=live ALLOW_PAID_PROVIDERS=TRUE FAKE_STACK_PAID=false
assert "  ...and creates nothing" no_post

run_case pass "happy path stops at AWAITING_APPROVAL" spend \
  PROVIDER_MODE=live ALLOW_PAID_PROVIDERS=true
assert "  ...default budget cap is 1.00" out_has "budget cap       USD 1.00"
assert "  ...creates the production" grep -q '^POST http://api.test/api/v1/productions$' "$WORK/calls.log"
assert "  ...sends budget, topic, theme and auto_approve=false" grep -qF \
  '{"theme_id": "time-traveler", "topic": "Eiffel Tower, 1889", "budget_limit_usd": "1.00", "auto_approve": false}' \
  "$WORK/calls.log.body"
assert "  ...prints the claims count" out_has "claims:          3 (unverified=1, verified=2)"
assert "  ...prints approved assets" out_has "approved assets: 2 of 3 candidates"
assert "  ...prints actual spend" out_has "actual spend:    USD 0.042100 of 1.00 limit"
assert "  ...never approves the production" eval '! grep -q "/approve" "$WORK/calls.log"'

run_case pass "continues with a warning when /providers is unavailable" spend \
  PROVIDER_MODE=live ALLOW_PAID_PROVIDERS=true FAKE_PROVIDERS=down
assert "  ...warns" out_has "WARNING: could not read"

run_case fail "fails when the production ends FAILED" spend \
  PROVIDER_MODE=live ALLOW_PAID_PROVIDERS=true FAKE_FINAL_STATE=FAILED
assert "  ...still reports spend" out_has "actual spend:"

echo
echo "demo_live selftest: $passed passed, $failed failed"
[ "$failed" -eq 0 ]
