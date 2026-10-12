#!/usr/bin/env bash
# Bootstrap a local development environment.
set -euo pipefail

cd "$(dirname "$0")/.."

python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'

echo
echo "Treble installed. Next steps:"
echo "  treble list"
echo "  ./scripts/run_von.sh   # start the Von decision server (Milestone 2)"
