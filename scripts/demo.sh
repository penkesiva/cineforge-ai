#!/usr/bin/env bash
# Create and run a sample production against the running stack (`make up` first).
# Overrides: API_URL, DASHBOARD_URL, THEME_ID, TOPIC, AUTO_APPROVE (true|false).
set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"
DASHBOARD_URL="${DASHBOARD_URL:-http://localhost:3000}"
THEME_ID="${THEME_ID:-time-traveler}"
TOPIC="${TOPIC:-The night the Eiffel Tower first lit up for the 1889 World's Fair}"
AUTO_APPROVE="${AUTO_APPROVE:-true}"

body=$(THEME_ID="$THEME_ID" TOPIC="$TOPIC" AUTO_APPROVE="$AUTO_APPROVE" python3 -c '
import json, os
print(json.dumps({
    "theme_id": os.environ["THEME_ID"],
    "topic": os.environ["TOPIC"],
    "auto_approve": os.environ["AUTO_APPROVE"].lower() == "true",
}))')

echo "POST $API_URL/api/v1/productions"
created=$(curl -fsS -X POST "$API_URL/api/v1/productions" \
  -H "Content-Type: application/json" -d "$body")
production_id=$(printf '%s' "$created" | python3 -c '
import json, sys
print(json.load(sys.stdin)["summary"]["id"])')
echo "created production $production_id"

echo "POST $API_URL/api/v1/productions/$production_id/run"
curl -fsS -X POST "$API_URL/api/v1/productions/$production_id/run" | python3 -c '
import json, sys
r = json.load(sys.stdin)
print("run accepted: state=%s job=%s" % (r["state"], r.get("job_id")))'

echo
echo "Watch it progress: $DASHBOARD_URL/productions/$production_id"
