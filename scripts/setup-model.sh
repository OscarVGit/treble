#!/usr/bin/env bash
# Download the distilled local model (treble-400m) from Hugging Face.
#
#   ./scripts/setup-model.sh
#
# Optional env overrides:
#   TREBLE_MODEL_REPO   HF repo (default: Oscar-veeee/treble-400m)
#   TREBLE_MODEL_DIR    destination (default: ~/.treble/models/treble-400m)
#   PYTHON              interpreter to use (default: repo .venv, else python3)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL_REPO="${TREBLE_MODEL_REPO:-Oscar-veeee/treble-400m}"
DEST="${TREBLE_MODEL_DIR:-$HOME/.treble/models/treble-400m}"

if [ -x "$ROOT/.venv/bin/python" ]; then
    PY="${PYTHON:-$ROOT/.venv/bin/python}"
else
    PY="${PYTHON:-python3}"
fi

mkdir -p "$DEST"

download_py() {
    "$PY" - "$MODEL_REPO" "$DEST" <<'PY'
import sys
from huggingface_hub import snapshot_download

snapshot_download(repo_id=sys.argv[1], local_dir=sys.argv[2])
PY
}

if command -v hf >/dev/null 2>&1; then
    echo "downloading $MODEL_REPO -> $DEST"
    hf download "$MODEL_REPO" --local-dir "$DEST"
elif "$PY" -c "import huggingface_hub" >/dev/null 2>&1; then
    echo "downloading $MODEL_REPO -> $DEST"
    download_py
else
    echo "installing huggingface_hub into: $PY"
    "$PY" -m pip install -q -U huggingface_hub
    echo "downloading $MODEL_REPO -> $DEST"
    download_py
fi

echo
echo "checkpoint: $DEST"
if command -v von >/dev/null 2>&1; then
    echo "serve it:   VON_CHECKPOINT_DIR=\"$DEST\" von serve"
else
    echo "von (von-sdk) is not installed. Install it to serve the model:"
    echo "  python -m pip install von-sdk"
    echo "  # or: python -m pip install \"git+https://github.com/wfzyx/von\""
    echo "then serve: VON_CHECKPOINT_DIR=\"$DEST\" von serve"
fi
echo "point Treble at it: export TREBLE_DECISION_URL=http://127.0.0.1:8765/v1/systemone"
