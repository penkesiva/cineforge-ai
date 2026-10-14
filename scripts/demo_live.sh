#!/usr/bin/env bash
# LIVE preproduction demo against the running stack. CAN SPEND REAL MONEY (Anthropic).
# Docs: docs/development/providers.md
#
# Refuses unless PROVIDER_MODE=live and ALLOW_PAID_PROVIDERS=true (environment first,
# then .env, like `docker compose`), and unless the running API reports the same.
# Asks you to type 'spend', creates a production capped at DEMO_BUDGET_USD with
# auto_approve off, waits until AWAITING_APPROVAL (research, script, storyboard only,
# no generation), then prints the claims count, approved assets and actual spend.
#
# Overrides: API_URL, DASHBOARD_URL, ENV_FILE, DEMO_BUDGET_USD (default 1.00), THEME_ID,
#            TOPIC, DEMO_TIMEOUT_SEC (default 900), DEMO_POLL_SEC (default 3).
# Compatible with macOS bash 3.2 (no python snippets inside $(...)).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"
API_URL="${API_URL:-http://localhost:8000}"
DASHBOARD_URL="${DASHBOARD_URL:-http://localhost:3000}"
DEMO_TIMEOUT_SEC="${DEMO_TIMEOUT_SEC:-900}"
DEMO_POLL_SEC="${DEMO_POLL_SEC:-3}"

# Last `KEY=value` in $ENV_FILE, without quotes or a trailing ` # comment`.
dotenv_get() {
  local key="$1" line value
  [ -f "$ENV_FILE" ] || return 0
  line=$(grep -E "^[[:space:]]*(export[[:space:]]+)?${key}[[:space:]]*=" "$ENV_FILE" | tail -n 1) || true
  [ -n "$line" ] || return 0
  value="${line#*=}"
  value="${value%%[[:space:]]#*}"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  if [[ "$value" == \"*\" || "$value" == \'*\' ]]; then
    value="${value:1:${#value}-2}"
  fi
  printf '%s' "$value"
}

# setting <NAME> <default>: environment (even if empty) wins over .env, then the default.
setting() {
  local value
  if printenv "$1" >/dev/null 2>&1; then
    value=$(printenv "$1")
  else
    value=$(dotenv_get "$1")
  fi
  printf '%s' "${value:-$2}"
}

lower() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }

refuse() {
  echo "demo-live: REFUSED - $1" >&2
  exit 1
}

provider_mode=$(lower "$(setting PROVIDER_MODE mock)")
allow_paid=$(lower "$(setting ALLOW_PAID_PROVIDERS false)")
budget=$(setting DEMO_BUDGET_USD 1.00)

[ "$provider_mode" = "live" ] ||
  refuse "PROVIDER_MODE=$provider_mode (needs live). Set PROVIDER_MODE=live in .env, then make up."
[ "$allow_paid" = "true" ] ||
  refuse "ALLOW_PAID_PROVIDERS=$allow_paid (needs true). Set it in .env, then make up."
usd_re='^[0-9]+(\.[0-9]{1,2})?$'
[[ "$budget" =~ $usd_re ]] ||
  refuse "DEMO_BUDGET_USD='$budget' is not a USD amount like 1.00"
[[ "$budget" =~ [1-9] ]] || refuse "DEMO_BUDGET_USD must be greater than 0"

export THEME_ID="${THEME_ID:-time-traveler}"
export TOPIC="${TOPIC:-Eiffel Tower, 1889}"
export BUDGET="$budget"

PY_STACK='
import json, sys
o = json.load(sys.stdin)
print("running stack: provider_mode=%s paid_providers_allowed=%s secrets_backend=%s"
      % (o.get("provider_mode"), o.get("paid_providers_allowed"), o.get("secrets_backend")))
for g in o.get("groups", []):
    print("  %-16s -> %s" % (g.get("capability"), g.get("active_provider") or "(none ready)"))
live = o.get("provider_mode") == "live" and o.get("paid_providers_allowed") is True
sys.exit(0 if live else 3)
'
PY_BODY='
import json, os
print(json.dumps({
    "theme_id": os.environ["THEME_ID"],
    "topic": os.environ["TOPIC"],
    "budget_limit_usd": os.environ["BUDGET"],
    "auto_approve": False,
}))
'
PY_ID='
import json, sys
print(json.load(sys.stdin)["summary"]["id"])
'
PY_RUN='
import json, sys
r = json.load(sys.stdin)
print("run accepted: state=%s job=%s" % (r["state"], r.get("job_id")))
'
PY_STATE='
import json, sys
print(json.load(sys.stdin)["summary"]["state"])
'
PY_REPORT='
import collections, json, sys
d = json.load(sys.stdin)
arts = d.get("artifacts") or {}
claims = (arts.get("research") or {}).get("claims") or []
by_status = collections.Counter(c.get("status", "?") for c in claims)
detail = ", ".join("%s=%d" % kv for kv in sorted(by_status.items()))
print("claims:          %d%s" % (len(claims), " (%s)" % detail if detail else ""))
media = arts.get("media") or {}
selected = set(media.get("selected_ids") or [])
candidates = media.get("candidates") or []
approved = [c for c in candidates
            if c.get("candidate_id") in selected and c.get("rights_status") == "approved"]
providers = collections.Counter(c.get("provider", "?") for c in approved)
pdetail = ", ".join("%s=%d" % kv for kv in sorted(providers.items()))
print("approved assets: %d of %d candidates%s (%d blocked by the rights gate)"
      % (len(approved), len(candidates), " (%s)" % pdetail if pdetail else "",
         len(media.get("blocked") or {})))
'
PY_COSTS='
import json, sys
c = json.load(sys.stdin)
cur = c.get("currency", "USD")
print("actual spend:    %s %.6f of %.2f limit (reserved %.6f, remaining %.6f)%s"
      % (cur, c.get("actual", 0), c.get("limit", 0), c.get("reserved", 0),
         c.get("remaining", 0), " [simulated]" if c.get("simulated") else ""))
for row in c.get("by_provider") or []:
    print("  %-20s %s %.6f (%d events)"
          % (row.get("label") or row.get("key"), cur, row.get("actual", 0),
             row.get("event_count", 0)))
'

echo "CineForge LIVE demo (preproduction only: stops at AWAITING_APPROVAL, no generation)"
echo "  API              $API_URL"
echo "  topic / theme    $TOPIC / $THEME_ID"
echo "  budget cap       USD $budget (hard cap: paid calls reserve against it first)"
echo "  settings         PROVIDER_MODE=$provider_mode ALLOW_PAID_PROVIDERS=$allow_paid"
echo

if overview=$(curl -fsS "$API_URL/api/v1/providers" 2>/dev/null); then
  if ! printf '%s' "$overview" | python3 -c "$PY_STACK"; then
    refuse "the running stack is not in live mode with paid providers allowed. Run make up after editing .env."
  fi
else
  echo "WARNING: could not read $API_URL/api/v1/providers; cannot confirm the running stack's settings."
fi
echo

echo "This can make PAID Anthropic calls (up to USD $budget) and real internet requests."
answer=""
read -r -p "Type 'spend' to continue: " answer || true
[ "$answer" = "spend" ] || { echo "Aborted. Nothing was created."; exit 1; }

body=$(python3 -c "$PY_BODY")
echo "POST $API_URL/api/v1/productions"
created=$(curl -fsS -X POST "$API_URL/api/v1/productions" \
  -H "Content-Type: application/json" -d "$body")
production_id=$(printf '%s' "$created" | python3 -c "$PY_ID")
echo "created production $production_id"

echo "POST $API_URL/api/v1/productions/$production_id/run"
curl -fsS -X POST "$API_URL/api/v1/productions/$production_id/run" | python3 -c "$PY_RUN"
echo "Watch it: $DASHBOARD_URL/productions/$production_id"
echo

deadline=$(($(date +%s) + DEMO_TIMEOUT_SEC))
state=""
last=""
while :; do
  detail=$(curl -fsS "$API_URL/api/v1/productions/$production_id")
  state=$(printf '%s' "$detail" | python3 -c "$PY_STATE")
  if [ "$state" != "$last" ]; then
    echo "state: $state"
    last="$state"
  fi
  case "$state" in
    DRAFT | RESEARCHING | SCRIPTING | STORYBOARDING) ;;
    *) break ;;
  esac
  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "Timed out after ${DEMO_TIMEOUT_SEC}s (state $state). It keeps running; cancel with:" >&2
    echo "  curl -X POST $API_URL/api/v1/productions/$production_id/cancel" >&2
    break
  fi
  sleep "$DEMO_POLL_SEC"
done

echo
echo "production:      $production_id ($state)"
printf '%s' "$detail" | python3 -c "$PY_REPORT"
curl -fsS "$API_URL/api/v1/productions/$production_id/costs" | python3 -c "$PY_COSTS"
echo
echo "Review claims and approve (or not) in the dashboard: $DASHBOARD_URL/productions/$production_id"

if [ "$state" != "AWAITING_APPROVAL" ]; then
  echo "demo-live: finished in $state, expected AWAITING_APPROVAL" >&2
  exit 1
fi
