#!/usr/bin/env bash
# Local end-to-end smoke test.
# Usage: ./scripts/run_e2e_local.sh [test_scenario]
# Default scenario: all
# Requires: BOT already running on port 8080 OR starts it automatically.

set -euo pipefail

SCENARIO="${1:-all}"
BOT_URL="${BOT_URL:-http://localhost:8080}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== Vera E2E Local Smoke Test ==="
echo "BOT_URL:  $BOT_URL"
echo "Scenario: $SCENARIO"
echo

# ─── Health check ─────────────────────────────────────────────────────────────
echo "--- Health check ---"
response=$(curl -sf "$BOT_URL/v1/healthz" || echo "FAIL")
if [[ "$response" == "FAIL" ]]; then
  echo "ERROR: bot not reachable at $BOT_URL — start it first:"
  echo "  uvicorn bot.main:app --port 8080 --workers 1"
  exit 1
fi
echo "$response"
echo

# ─── Metadata check ───────────────────────────────────────────────────────────
echo "--- Metadata check ---"
curl -sf "$BOT_URL/v1/metadata" | python3 -m json.tool
echo

# ─── Run judge simulator ──────────────────────────────────────────────────────
echo "--- Running judge_simulator.py (scenario=$SCENARIO) ---"
cd "$ROOT"

if [[ -f .env ]]; then
  # shellcheck disable=SC2046
  export $(grep -v '^#' .env | xargs)
fi

BOT_URL="$BOT_URL" TEST_SCENARIO="$SCENARIO" python3 judge_simulator.py

echo
echo "=== Done ==="
