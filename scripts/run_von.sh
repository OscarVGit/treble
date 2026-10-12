#!/usr/bin/env bash
# Start the local Von decision-model server.
#
# Uses the checkpoint in VON_CHECKPOINT_DIR (default: the sibling Von
# checkout's local weights). Requires the `von` CLI on PATH — install it
# into its own environment first (Python >= 3.12):
#
#   python3 -m venv ~/Desktop/Von/.venv
#   ~/Desktop/Von/.venv/bin/pip install -e ~/Desktop/Von/von
#   export PATH="$HOME/Desktop/Von/.venv/bin:$PATH"
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p .treble

export VON_CHECKPOINT_DIR="${VON_CHECKPOINT_DIR:-$HOME/Desktop/Von/von_model/von}"
export VON_CHAINS_DIR="${VON_CHAINS_DIR:-off}"

if ! command -v von >/dev/null 2>&1; then
  echo "error: 'von' CLI not found on PATH." >&2
  echo "Install von-sdk (pip install -e <von repo>) and retry." >&2
  exit 1
fi

exec von serve --host 127.0.0.1 --port "${TREBLE_VON_PORT:-8765}" \
  >> .treble/von.log 2>&1
