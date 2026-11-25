#!/usr/bin/env bash
# One-command bootstrap + runner for the Treble demo.
#
#   cd treble_demo
#   ./run.sh
#
# First run:
#   - creates ./.venv with Python >= 3.12
#   - installs Treble, von-sdk, and huggingface_hub
#   - downloads treble-400m from Hugging Face (~3 GB, once)
#   - starts the local Von server
#   - runs the Old Way and the Treble Way
#
# Later runs reuse the venv, the cached model, and (if still up) the server.
#
# Env overrides:
#   TREBLE_PYTHON      Python >=3.12 used to create .venv
#   TREBLE_MODEL_DIR   model cache (default: ~/.treble/models/treble-400m)
#   TREBLE_MODEL_REPO  Hugging Face repo (default: Oscar-veeee/treble-400m)
#   TREBLE_VON_PORT    Von port (default: 8765)
#   KEEP_VON=1         leave a server started by this script running on exit
set -euo pipefail

DEMO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$DEMO_DIR/.." && pwd)"
VENV="$DEMO_DIR/.venv"
MODEL_DIR="${TREBLE_MODEL_DIR:-$HOME/.treble/models/treble-400m}"
MODEL_REPO="${TREBLE_MODEL_REPO:-Oscar-veeee/treble-400m}"
VON_PORT="${TREBLE_VON_PORT:-8765}"
HEALTH_URL="http://127.0.0.1:${VON_PORT}/health"
DECISION_URL="http://127.0.0.1:${VON_PORT}/v1/systemone"

find_python() {
    local candidate
    for candidate in "${TREBLE_PYTHON:-}" python3.14 python3.13 python3.12 python3; do
        [ -n "$candidate" ] || continue
        if command -v "$candidate" >/dev/null 2>&1 \
            && "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' >/dev/null 2>&1; then
            command -v "$candidate"
            return 0
        fi
    done
    return 1
}

health() {
    "$VENV/bin/python" - "$HEALTH_URL" <<'PY' >/dev/null 2>&1
import sys
import urllib.request

urllib.request.urlopen(sys.argv[1], timeout=1).read()
PY
}

# 1. Python >= 3.12 and a dedicated venv.
if [ -x "$VENV/bin/python" ]; then
    if ! "$VENV/bin/python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)'; then
        echo "error: $VENV uses Python < 3.12." >&2
        echo "       Remove treble_demo/.venv and re-run ./run.sh." >&2
        exit 1
    fi
else
    PY="$(find_python)" || {
        cat >&2 <<'EOF'
error: this demo needs Python >= 3.12 (for von-sdk).

Install it and re-run:
  macOS:  brew install python@3.12
  uv:     uv python install 3.12
  or set TREBLE_PYTHON=/path/to/python3.12
EOF
        exit 1
    }
    echo "Creating demo venv with $PY ..."
    "$PY" -m venv "$VENV"
fi

export PATH="$VENV/bin:$PATH"

# 2. Python packages.
if [ ! -x "$VENV/bin/treble" ]; then
    echo "Installing Treble from $REPO_ROOT ..."
    "$VENV/bin/python" -m pip install --upgrade pip
    "$VENV/bin/pip" install -e "$REPO_ROOT"
fi

if [ ! -x "$VENV/bin/von" ]; then
    echo "Installing von-sdk ..."
    "$VENV/bin/pip" install "von-sdk>=1.3"
fi

if ! "$VENV/bin/python" -c "import huggingface_hub" >/dev/null 2>&1; then
    echo "Installing huggingface_hub ..."
    "$VENV/bin/pip" install huggingface_hub
fi

# 3. Model checkpoint (download once, resume on interruption).
MODEL_OK=1
for file in model.safetensors option_marker.pt config.json \
    tokenizer.json tokenizer_config.json marker_calibration.json; do
    if [ ! -f "$MODEL_DIR/$file" ]; then
        MODEL_OK=0
        break
    fi
done

if [ "$MODEL_OK" = 1 ]; then
    echo "Using cached model: $MODEL_DIR"
else
    echo "Downloading $MODEL_REPO to $MODEL_DIR (one-time, ~3 GB) ..."
    mkdir -p "$MODEL_DIR"
    "$VENV/bin/python" - "$MODEL_REPO" "$MODEL_DIR" <<'PY'
import sys

from huggingface_hub import snapshot_download

snapshot_download(repo_id=sys.argv[1], local_dir=sys.argv[2])
PY
fi

# 4. Registry sanity check.
REGISTRY="$DEMO_DIR/.treble/procedures/run-thursday-vba.yaml"
if [ ! -f "$REGISTRY" ]; then
    echo "error: missing registry entry: $REGISTRY" >&2
    echo "       Re-clone the repo or restore treble_demo/.treble/procedures/." >&2
    exit 1
fi

# 5. Start or reuse the local Von server.
VON_PID=""
STARTED_VON=0
cleanup() {
    if [ "$STARTED_VON" = 1 ] && [ "${KEEP_VON:-0}" != 1 ]; then
        kill "$VON_PID" 2>/dev/null || true
        wait "$VON_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

if health; then
    echo "Using existing Von server on port $VON_PORT"
else
    echo "Starting Von server on port $VON_PORT ..."
    mkdir -p "$DEMO_DIR/.treble"
    VON_CHECKPOINT_DIR="$MODEL_DIR" VON_CHAINS_DIR=off \
        "$VENV/bin/von" serve --host 127.0.0.1 --port "$VON_PORT" \
        >"$DEMO_DIR/.treble/von.log" 2>&1 &
    VON_PID=$!
    STARTED_VON=1

    for _ in $(seq 1 120); do
        if health; then
            break
        fi
        sleep 1
    done
    if ! health; then
        echo "error: Von did not become healthy; see $DEMO_DIR/.treble/von.log" >&2
        tail -30 "$DEMO_DIR/.treble/von.log" >&2 || true
        exit 1
    fi
fi

# 6. Run both sides.
echo
echo "============================================================"
echo " OLD WAY - the full five-flag invocation by hand"
echo "============================================================"
( cd "$DEMO_DIR" && ./scripts/old_way.sh )

echo
echo "============================================================"
echo " TREBLE WAY - one natural-language command"
echo "============================================================"
( cd "$DEMO_DIR" && TREBLE_DECISION_URL="$DECISION_URL" \
    "$VENV/bin/treble" "run thursday vba" )

echo
echo "Demo complete."
echo
echo "Treble Way command:"
echo "  cd treble_demo"
echo "  TREBLE_DECISION_URL=$DECISION_URL .venv/bin/treble \"run thursday vba\""
if [ "$STARTED_VON" = 1 ] && [ "${KEEP_VON:-0}" != 1 ]; then
    echo
    echo "Von was stopped. Re-run ./run.sh, or start it with KEEP_VON=1 to keep it up."
fi
