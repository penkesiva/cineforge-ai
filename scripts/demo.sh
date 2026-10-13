#!/usr/bin/env bash
# Create and run a sample production against the running stack (`make up` first).
# Overrides: API_URL, DASHBOARD_URL, THEME_ID, TOPIC, AUTO_APPROVE (true|false).
# Compatible with macOS bash 3.2 (no python snippets inside $(...)).
set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"
DASHBOARD_URL="${DASHBOARD_URL:-http://localhost:3000}"
DEFAULT_TOPIC="The night the Eiffel Tower first lit up for the 1889 World's Fair"
export THEME_ID="${THEME_ID:-time-traveler}"
export TOPIC="${TOPIC:-$DEFAULT_TOPIC}"
export AUTO_APPROVE="${AUTO_APPROVE:-true}"

PY_BODY='
import json, os
print(json.dumps({
    "theme_id": os.environ["THEME_ID"],
    "topic": os.environ["TOPIC"],
    "auto_approve": os.environ["AUTO_APPROVE"].lower() == "true",
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

body=$(python3 -c "$PY_BODY")

echo "POST $API_URL/api/v1/productions"
created=$(curl -fsS -X POST "$API_URL/api/v1/productions" \
  -H "Content-Type: application/json" -d "$body")
production_id=$(printf '%s' "$created" | python3 -c "$PY_ID")
echo "created production $production_id"

echo "POST $API_URL/api/v1/productions/$production_id/run"
curl -fsS -X POST "$API_URL/api/v1/productions/$production_id/run" | python3 -c "$PY_RUN"

echo
echo "Watch it progress: $DASHBOARD_URL/productions/$production_id"
