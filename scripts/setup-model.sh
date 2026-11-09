#!/usr/bin/env bash
# Download the distilled local model (treble-400m) from Hugging Face.
#
#   ./scripts/setup-model.sh              # checkpoint only
#   ./scripts/setup-model.sh --with-von   # checkpoint + von-sdk server
#
# Optional env overrides:
#   TREBLE_MODEL_REPO   HF repo (default: Oscar-veeee/treble-400m)
#   TREBLE_MODEL_DIR    destination (default: ~/.treble/models/treble-400m)
#   PYTHON              interpreter for the HF download (default: repo .venv, else python3)
#   VON_PYTHON          Python >=3.12 used to create the von-sdk venv
#   VON_VENV            venv for von-sdk (default: ~/.treble/venvs/von)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL_REPO="${TREBLE_MODEL_REPO:-Oscar-veeee/treble-400m}"
DEST="${TREBLE_MODEL_DIR:-$HOME/.treble/models/treble-400m}"
VON_VENV="${VON_VENV:-$HOME/.treble/venvs/von}"

usage() {
    cat <<'EOF'
usage: ./scripts/setup-model.sh [--with-von]

Downloads the distilled treble-400m checkpoint. With --with-von, also installs
the von-sdk server into a dedicated Python >= 3.12 venv.

env overrides:
  TREBLE_MODEL_REPO   HF repo (default: Oscar-veeee/treble-400m)
  TREBLE_MODEL_DIR    destination (default: ~/.treble/models/treble-400m)
  PYTHON              interpreter for the HF download
  VON_PYTHON          Python >=3.12 used to create the von-sdk venv
  VON_VENV            venv for von-sdk (default: ~/.treble/venvs/von)
EOF
}

WITH_VON=false
for arg in "$@"; do
    case "$arg" in
        --with-von|--von) WITH_VON=true ;;
        -h|--help) usage; exit 0 ;;
        *)
            echo "error: unknown argument: $arg" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [ -x "$ROOT/.venv/bin/python" ]; then
    PY="${PYTHON:-$ROOT/.venv/bin/python}"
else
    PY="${PYTHON:-python3}"
fi

download_py() {
    "$PY" - "$MODEL_REPO" "$DEST" <<'PY'
import sys
from huggingface_hub import snapshot_download

snapshot_download(repo_id=sys.argv[1], local_dir=sys.argv[2])
PY
}

find_von_python() {
    local candidate
    for candidate in "${VON_PYTHON:-}" python3.14 python3.13 python3.12 python3; do
        [ -n "$candidate" ] || continue
        if command -v "$candidate" >/dev/null 2>&1 \
            && "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' >/dev/null 2>&1; then
            command -v "$candidate"
            return 0
        fi
    done
    return 1
}

install_von() {
    local py
    if ! py="$(find_von_python)"; then
        echo "error: von-sdk requires Python >= 3.12, but no compatible interpreter was found." >&2
        echo "       Set VON_PYTHON=/path/to/python3.12 and re-run with --with-von." >&2
        return 1
    fi

    if [ -x "$VON_VENV/bin/von" ]; then
        echo "von-sdk already installed: $VON_VENV/bin/von"
        return 0
    fi

    echo "creating von-sdk venv: $VON_VENV (using $py)"
    "$py" -m venv "$VON_VENV"
    "$VON_VENV/bin/python" -m pip install --upgrade pip
    "$VON_VENV/bin/pip" install "von-sdk>=1.3"
    echo "installed: $VON_VENV/bin/von"
}

mkdir -p "$DEST"

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

VON_BIN=""
if [ "$WITH_VON" = true ]; then
    install_von
    VON_BIN="$VON_VENV/bin/von"
elif command -v von >/dev/null 2>&1; then
    VON_BIN="$(command -v von)"
fi

echo
echo "checkpoint: $DEST"
if [ -n "$VON_BIN" ]; then
    echo "serve it:   VON_CHECKPOINT_DIR=\"$DEST\" \"$VON_BIN\" serve --host 127.0.0.1 --port 8765"
else
    echo "von (von-sdk) is not installed. Re-run with --with-von, or install it:"
    echo "  VON_PYTHON=python3.12 ./scripts/setup-model.sh --with-von"
    echo "  # manual: python3.12 -m venv ~/.treble/venvs/von"
    echo "  #         ~/.treble/venvs/von/bin/pip install von-sdk"
    echo "then serve: VON_CHECKPOINT_DIR=\"$DEST\" ~/.treble/venvs/von/bin/von serve"
fi
echo "point Treble at it: export TREBLE_DECISION_URL=http://127.0.0.1:8765/v1/systemone"
