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
that fixes an environment issue), register it so future sessions reuse it.
When the user asks to "add this command to Treble", follow the registration
workflow below.

Mark `risk` honestly: `read-only` runs without a prompt; `mutating`/`destructive`
procedures (and `treble remove`) confirm before executing. Pass `--yes` only
when the action is clearly intended and safe. Confirmation follows the declared
`risk`, not the command text.

## Registering a command from a user request

Follow the full checklist in `AGENTS.md` ("Registering a command from a user
request"). Minimum sequence:

1. `treble list`; read `.treble/procedures/*.yaml`; reuse an existing
   procedure or extend it with an alias instead of creating a near-duplicate.
2. Choose a kebab-case, verb-led name; avoid prefix/near-duplicate names; give
   distinct aliases.
3. Write a routing-friendly description with likely user phrasings and
   synonyms; keep it one or two sentences.
4. Classify risk honestly (`read-only`/`mutating`/`destructive`); use project
   scope unless machine-specific.
5. Register with the positional command form (there is no `--command` flag):
   `treble-add "<exact command>" --name <slug> --description "..." --risk ...`
6. Verify with `treble show`, `treble explain`, `treble --dry-run`, and
   `treble test` only when safe.
7. Tell the user the canonical name, aliases, a natural-language example, and
   whether the risk will prompt.

See `AGENTS.md` for worked examples, overwrite/alias rules, and the MCP caveat
(no add/register tool).

## MCP

If your client speaks MCP, the `treble-mcp` server exposes the same operations as
tools (`list_procedures`, `show_procedure`, `explain_procedure`, `run`, `test`,
`remove`, `stats`). It does **not** expose an add/register tool; use
`treble-add` as described above. A mutating/destructive tool call with
`yes=false` returns `status: "confirmation_required"` with a prompt — ask the
human, then re-call with `yes=true`.

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
