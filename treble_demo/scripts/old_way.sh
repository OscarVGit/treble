#!/usr/bin/env bash
# OLD WAY — the exact command to type or paste during the demo.
#
# Run from inside treble_demo/. Five required flags, three paths, one ISO
# date, one macro name, and a --verbose flag that is required for no good
# reason. Nothing here is registered; you have to remember all of it.
#
# Compare with the Treble Way:
#   treble "run thursday vba"
set -euo pipefail

TZ="America/New_York" \
VBA_REPORT_PROFILE="weekly-report-production" \
VBA_LOG_LEVEL="DEBUG" \
python3 ./scripts/run_vba_macro.py \
  --config-path ./config/weekly_report.json \
  --target-date 2026-11-05 \
  --macro-name ThursdayWeeklyReport \
  --output-dir ./output/2026/11/05/thursday-weekly-report \
  --verbose
