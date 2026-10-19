# CLAUDE.md

Guidance for Claude Code in this repository and in projects that use Treble.
`AGENTS.md` is the authoritative version; this file mirrors the essentials.

## Use the command registry

Prefer registered procedures over re-deriving flags:

- `treble list` — registered procedures (name, risk, description).
- `treble <name>` / `treble "run the checks"` — execute by name or intent.
- `treble test <name>` — deterministic run by name (no model).
- `treble explain <name>` — exact argv and working directory.
- `treble --dry-run <name>` — preview without executing.
- `treble stats` — usage summary of past invocations.

When you find a reliable, non-obvious invocation (a working flag set, a script
that fixes an environment issue), register it so future sessions reuse it:

    treble-add "<exact command>" --name <slug> --description "<what it does>" --risk read-only|mutating|destructive

Mark `risk` honestly: `read-only` runs without a prompt; `mutating`/`destructive`
procedures (and `treble remove`) confirm before executing. Pass `--yes` only
when the action is clearly intended and safe. Confirmation follows the declared
`risk`, not the command text.

## MCP

If your client speaks MCP, the `treble-mcp` server exposes the same operations as
tools (`list_procedures`, `show_procedure`, `explain_procedure`, `run`, `test`,
`remove`, `stats`). A mutating/destructive tool call with `yes=false` returns
`status: "confirmation_required"` with a prompt — ask the human, then re-call
with `yes=true`.

## Developing this repo

- Setup: `python -m venv .venv && .venv/bin/pip install -e .`
- Tests: `.venv/bin/python -m pytest`
- Lint: `.venv/bin/ruff check src tests evals`
- Decision service (for free-form routing): `scripts/run_von.sh`
- End-to-end CLI smoke: `scripts/smoke_test.sh` (needs Von running)
- Routing eval: `.venv/bin/python evals/run_eval.py evals/scenarios/routing.yaml`
  (add `--fake` to run offline; `--repeat 3` to check variance)

Prefer `treble test <name>` / argument forwarding for deterministic execution;
only free-form requests go through the decision model. Do not commit unless
asked.
