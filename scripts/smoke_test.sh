#!/usr/bin/env bash
#
# Treble CLI smoke harness.
#
# Runs the *real* `treble` CLI end-to-end against a fresh fixture registry
# and reports PASS/FAIL per case. Complements evals/run_eval.py (which
# measures the decision model's routing score); this checks the whole
# pipeline: dispatch -> Von routing -> policy -> runtime -> audit.
#
# Adding a case is one line — see run_case calls below. Extend freely; the
# format is intentionally tabular so the suite can grow into a regular
# eval run (CI: call this with TREBLE set, assert exit code 0).
#
# Env overrides:
#   TREBLE          path to the treble binary          (default: repo .venv)
#   TREBLE_ADD      path to treble-add                  (default: alongside TREBLE)
#   TREBLE_VON_URL  von endpoint                        (default: 127.0.0.1:8765)
#   SMOKE_DIR       scratch dir to use                  (default: mktemp)
#   TREBLE_SMOKE_ONLY   run a single case by name (substring match)
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TREBLE="${TREBLE:-$ROOT/.venv/bin/treble}"
TREBLE_ADD="${TREBLE_ADD:-$ROOT/.venv/bin/treble-add}"
VON_URL="${TREBLE_VON_URL:-http://127.0.0.1:8765/v1/systemone}"

PASS=0
FAIL=0
declare -a FAILURES=()

usage() {
  echo "usage: $0 [--keep] [--only <name-substr>]"
  echo "  --keep     keep the scratch directory on failure"
  echo "  --only X   run only cases whose name contains X"
  exit 0
}

run_case() {
  # run_case "<name>" <expected_exit> "<expected_substring>" -- <cmd> [args...]
  local name="$1"; shift
  local expect_exit="$1"; shift
  local expect_sub="$1"; shift
  require_sep=false
  [ "$1" = "--" ] && shift

  local out rc
  out="$(cd "$SMOKE_DIR" && "$@" </dev/null 2>&1)"
  rc=$?

  local ok=true reason=""
  if [ "$rc" -ne "$expect_exit" ]; then
    ok=false; reason="exit=$rc (want $expect_exit)"
  elif [ -n "$expect_sub" ] && ! grep -qF -- "$expect_sub" <<<"$out"; then
    ok=false; reason="output missing: $expect_sub"
  fi

  if [ "$ok" = true ]; then
    PASS=$((PASS + 1))
    printf '  \033[32mPASS\033[0m %s\n' "$name"
  else
    FAIL=$((FAIL + 1))
    FAILURES+=("$name: $reason")
    printf '  \033[31mFAIL\033[0m %s  (%s)\n' "$name" "$reason"
    printf '       --- output ---\n%s\n       ---------------\n' "$out"
  fi
}

require() { command -v "$1" >/dev/null 2>&1 || { echo "error: '$1' not found" >&2; exit 2; }; }

GOT_VON=false
von_health() { curl -fsS --max-time 3 "${VON_URL%/v1/systemone}/health" >/dev/null 2>&1; }

# ---------------------------------------------------------------------------
# parse args + preflight
# ---------------------------------------------------------------------------
ONLY=""
KEEP=false
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage ;;
    --only) shift; ONLY="$1" ;;
    --keep) KEEP=true ;;
    *) echo "unknown arg: $1" >&2; usage ;;
  esac
  shift
done

require "$TREBLE"
require "$TREBLE_ADD"

if ! von_health; then
  echo "error: Von server unreachable at ${VON_URL%/v1/systemone}" >&2
  echo "       start it with: scripts/run_von.sh  (or set TREBLE_VON_URL)" >&2
  exit 3
fi

SMOKE_DIR="${SMOKE_DIR:-$(mktemp -d /tmp/treble-smoke.XXXXXX)}"
export TREBLE_VON_URL="$VON_URL"

echo "treble:  $TREBLE"
echo "variant: $([ -n "$ONLY" ] && echo "only '$ONLY'" || echo all)"
echo "scratch: $SMOKE_DIR"
echo

# ---------------------------------------------------------------------------
# fixture registry (registered inside SMOKE_DIR so treble sees them)
# ---------------------------------------------------------------------------
( cd "$SMOKE_DIR" && \
  "$TREBLE_ADD" "echo hello-treble" --name hello --description "Say hello" >/dev/null && \
  "$TREBLE_ADD" "echo build-done" --name build --description "Build the project" >/dev/null && \
  "$TREBLE_ADD" "echo checks-nv" --name check-no-verify \
    --description "Run project checks without verification" >/dev/null && \
  "$TREBLE_ADD" "definitely-not-a-real-binary --flag" --name broken \
    --description "Always fails to launch" >/dev/null ) || {
  echo "error: fixture registration failed" >&2; exit 1;
}

want_case() {
  # run only if --only matches
  [ -n "$ONLY" ] && [[ "$1" != *"$ONLY"* ]] && return 1
  return 0
}

run() { # run <name> <exit> <sub> -- <cmd...>   (respects --only)
  local name="$1"
  want_case "$name" || return
  run_case "$@"
}

# run_relaxed: pass if the request runs the right thing OR escalates safely.
# Fail only on wrong execution. Encodes the "ask rather than guess" safety
# property from the README — the core invariant the eval suite must hold.
run_relaxed() {
  local name="$1"; shift        # <name> <run_substring> -- <cmd...>
  local run_sub="$1"; shift
  [ "$1" = "--" ] && shift
  want_case "$name" || return

  local out rc ok=true reason=""
  out="$(cd "$SMOKE_DIR" && "$@" </dev/null 2>&1)"
  rc=$?
  if [ "$rc" -eq 0 ] && grep -qF -- "$run_sub" <<<"$out"; then
    :
  elif [ "$rc" -eq 3 ] && grep -qF -- "no suitable action" <<<"$out"; then
    :   # safe escalation — acceptable outcome
  else
    ok=false; reason="unexpected: exit=$rc"
  fi
  if [ "$ok" = true ]; then
    PASS=$((PASS + 1)); printf '  \033[32mPASS\033[0m %s (safe-outcome)\n' "$name"
  else
    FAIL=$((FAIL + 1)); FAILURES+=("$name: $reason")
    printf '  \033[31mFAIL\033[0m %s  (%s)\n' "$name" "$reason"
    printf '       --- output ---\n%s\n       ---------------\n' "$out"
  fi
}

echo "# execution — bare names and phrasing"
run "bare name hello"          0 "hello-treble" -- "$TREBLE" hello
run "bare name build"          0 "build-done" -- "$TREBLE" build
run "run subcommand hello"     0 "hello-treble" -- "$TREBLE" run hello
run "nl run the hello task"    0 "hello-treble" -- "$TREBLE" run the hello task
run_relaxed "nl just say hello" "hello-treble" -- "$TREBLE" just say hello please

echo
echo "# flag ownership — positional: leading flags are Treble's"
run "global dry-run leading"   0 "[dry-run] would execute: echo hello-treble" -- "$TREBLE" --dry-run hello
run "global dry-run+yes"       0 "[dry-run] would execute: echo hello-treble" -- "$TREBLE" --yes --dry-run hello
run "trailing flag forwarded"  0 "hello-treble --verbose" -- "$TREBLE" hello --verbose
run "unknown leading flag"     2 "unknown Treble option" -- "$TREBLE" --watch hello

echo
echo "# argument forwarding — name/command + trailing flags (no Von)"
run "forward name+flag"        0 "checks-nv --watch" -- "$TREBLE" check-no-verify --watch
run "forward command+flag"     0 "build-done --watch" -- "$TREBLE" echo build-done --watch
run "forward multi extras"     0 "hello-treble -m hi --verbose" -- "$TREBLE" hello -m hi --verbose
run "no forward bare name"     0 "hello-treble" -- "$TREBLE" hello

echo
echo "# execution — command-shaped / README examples"
run "verbatim pnpm run build"  0 "build-done" -- "$TREBLE" pnpm run build
run "check without verification" 0 "checks-nv" -- "$TREBLE" pnpm run check without verification

echo
echo "# control plane — free-form (accuracy of NL actions is scored by"
echo "#   evals/run_eval.py; smoke only enforces safe outcomes here)"
run "nl list everything"       0 "check-no-verify" -- "$TREBLE" list all procedures
run_relaxed "nl show hello" "hello-treble" -- "$TREBLE" show me the hello procedure
run "nl explain hello"         0 "argv:" -- "$TREBLE" explain the hello procedure
run "nl remove dry-run"        0 "[dry-run] would remove 'hello'" -- "$TREBLE" --dry-run remove the hello procedure
run "nl add hint"              3 "treble-add" -- "$TREBLE" add a new procedure

echo
echo "# literal subcommands — deterministic, no Von"
run "literal list"             0 "Say hello" -- "$TREBLE" list
run "literal show hello"       0 "executable: echo" -- "$TREBLE" show hello
run "literal explain hello"    0 "argv:" -- "$TREBLE" explain hello
run "dispatch freeform remove" 0 "[dry-run] would remove 'hello'" -- "$TREBLE" run --dry-run remove the hello procedure


echo
echo "# safety / escalation"
run "unrelated weather"        3 "no suitable action" -- "$TREBLE" what is the weather today
run "broken procedure test"    5 "" -- "$TREBLE" test broken

echo
echo "# registration errors"
run "duplicate add"            1 "already exists" -- "$TREBLE_ADD" "echo x" --name build --description "dupe"
run "overwrite add"            0 "registered 'build'" -- "$TREBLE_ADD" "echo build-done" --name build --description "replaced" --overwrite

echo
echo "# summary: $PASS passed, $FAIL failed"
if [ "$FAIL" -gt 0 ]; then
  printf '  \033[31mfailures:\033[0m\n'
  for f in "${FAILURES[@]}"; do printf '  - %s\n' "$f"; done
  [ "$KEEP" = false ] && rm -rf "$SMOKE_DIR"
  exit 1
fi
[ "$KEEP" = false ] && rm -rf "$SMOKE_DIR"
echo "  all green"