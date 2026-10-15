# AGENTS.md

Guidance for AI agents working in this repository or in projects that use
Treble.

## Command registry (Treble)

This repo keeps known-good command invocations in Treble. Prefer it over
re-deriving flags each time:

- `treble list` — registered procedures (name, risk, description).
- `treble test <name>` — run a registered procedure by name (deterministic, no model).
- `treble <name> [flags]` — run it, forwarding trailing flags to the stored command.
- `treble explain <name>` — show the exact argv and working directory.
- `treble --dry-run <name>` — preview without executing.
- `treble stats` — usage summary of past invocations.

When you find a reliable, non-obvious invocation (a working flag set, a script
that fixes an environment issue), register it so future sessions reuse it:

    treble-add "<exact command>" --name <slug> --description "<what it does>" --risk read-only|mutating|destructive

Mark `risk` honestly: `read-only` runs without a prompt; `mutating`/`destructive`
procedures (and `treble remove`) confirm before executing — pass `--yes` only
when the action is clearly intended and safe. Confirmation follows the declared
`risk`, not the command text.

If your client speaks MCP, the `treble-mcp` server exposes the same operations
as tools (`list_procedures`, `run`, `test`, `remove`, `stats`); a mutating tool
call with `yes=false` returns `confirmation_required` — ask the human, then
re-call with `yes=true`.

## Developing this repo

- Setup: `python -m venv .venv && .venv/bin/pip install -e .`
- Tests: `.venv/bin/python -m pytest`
- Lint: `.venv/bin/ruff check src tests evals`
- Decision service (required for free-form routing): `scripts/run_von.sh`
- End-to-end CLI smoke: `scripts/smoke_test.sh` (needs Von running)
- Routing eval: `.venv/bin/python evals/run_eval.py evals/scenarios/routing.yaml`
  (add `--fake` to run offline; `--repeat 3` to check variance)

Prefer `treble test <name>` / argument forwarding for deterministic execution;
only free-form requests go through the decision model. Do not commit unless
asked.
