#!/usr/bin/env bash
# run_daily.sh — daily lifecycle for the Kaiju Kalshi weather-temp bot.
#
# Sequence: settle YESTERDAY → retrain calibration → run TODAY's intraday window.
#
# SECRETS / MODE: All secrets (KALSHI_KEY_ID, KALSHI_PRIVATE_KEY) and mode
# configuration (KAIJU_MODE, KAIJU_CITIES) are sourced from the environment —
# either from launchd EnvironmentVariables (macOS plist) or a mounted .env file
# (EC2). Nothing is hardcoded here.
#
# TOLERANCES:
#   settle and retrain use || true so a not-yet-ready settlement (data lag) or a
#   retrain failure (no data yet) does NOT abort the intraday trading run. The
#   run step is the critical long-running command and is NOT wrapped in || true.
#
# PORTABILITY: GNU date (Linux/EC2) and BSD date (macOS) are both handled via
# the fallback expression on the YESTERDAY line below.

set -euo pipefail

# Derive absolute repo root from the directory containing this script.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

# --- Configuration from environment (with sensible defaults) ---
STATION="${KAIJU_CITY:-NYC}"
# MODE is read by kaiju.runner directly from KAIJU_MODE env var; exported here
# for visibility in logs if needed.
MODE="${KAIJU_MODE:-shadow-paper}"

# --- Dates ---
# Portable YESTERDAY: try GNU date first (Linux/EC2), fall back to BSD date (macOS).
YESTERDAY="$(date -d 'yesterday' +%F 2>/dev/null || date -v-1d +%F)"
TODAY="$(date +%F)"

# --- Banner ---
echo "============================================================"
echo "  Kaiju daily run  |  $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "  station=${STATION}  mode=${MODE}"
echo "  yesterday=${YESTERDAY}  today=${TODAY}"
echo "============================================================"

# --- Step 1: Settle yesterday ---
# || true: a not-yet-ready settlement (LookupError from IEM) must not block trading.
echo "[$(date -u +%T)] Step 1/3 — settle ${STATION} ${YESTERDAY}"
uv run python -m kaiju.runner settle --station "${STATION}" --date "${YESTERDAY}" || true

# --- Step 2: Retrain calibration ---
# || true: no data yet / retrain failure must not block intraday run.
echo "[$(date -u +%T)] Step 2/3 — retrain ${STATION}"
uv run python -m kaiju.runner retrain --station "${STATION}" || true

# --- Step 3: Run intraday loop (long-running; exits at day time-stop) ---
# NOT wrapped in || true — this is the primary command; failures should surface.
echo "[$(date -u +%T)] Step 3/3 — run ${STATION} (long-running until time-stop)"
uv run python -m kaiju.runner run --station "${STATION}"

echo "[$(date -u +%T)] Kaiju daily run complete."
