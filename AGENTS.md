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
that fixes an environment issue), register it so future sessions reuse it.
When the user asks to "add this command to Treble" or to register something,
follow the workflow below instead of guessing or hand-editing YAML.

Mark `risk` honestly: `read-only` runs without a prompt; `mutating`/`destructive`
procedures (and `treble remove`) confirm before executing — pass `--yes` only
when the action is clearly intended and safe. Confirmation follows the declared
`risk`, not the command text.

## Registering a command from a user request

### 1. Inspect the existing registry first

- Run `treble list` to see names, risk, and descriptions.
- Read `.treble/procedures/*.yaml` (project) and `~/.treble/procedures/*.yaml`
  (personal) when you need exact argv, aliases, or scope.
- Use `treble show <name>` / `treble explain <name>` on close candidates.

Look for:

- an equivalent command/argv — reuse it instead of duplicating;
- a name or alias collision — do not create a near-duplicate;
- an existing procedure that only needs an alias or an `--overwrite` update.

If an equivalent procedure exists, prefer reusing it. Add an alias only when
the new phrase is genuinely useful, and preserve existing aliases when
re-registering (see "Updating an existing procedure" below).

### 2. Choose the identity

- Name: kebab-case, verb-led, stable, no spaces, no leading `-`.
  Good: `run-weekly-report`, `check-no-verify`, `test-cli`.
- Avoid names that are prefixes of one another or differ only by a suffix
  (`check` vs `check-no-verify`): Treble's collision handling treats these as
  ambiguous.
- Aliases: short, distinct, natural-language-friendly; repeat `--alias` for
  each. Do not reuse another procedure's name or alias.
- Treble does not template parameters. Register a concrete invocation; for
  alternatives, register distinct variants with distinct names/aliases.

### 3. Write a routing-friendly description

The decision model sees the name + description in the routing state, and the
name + description + exact command + aliases in the option text. Write for
both a human and the router:

- what it does and what it produces;
- likely user phrasings and synonyms (e.g. "run thursday vba",
  "execute weekly report macro");
- the tool/artifact (pytest, pnpm, Excel/VBA, docker);
- likely misspellings only when useful (e.g. "thursda");
- what it is **not** for when confusion is likely.

Keep it to one or two sentences. Do not paste the full argv into the
description.

### 4. Classify side effects, scope, and execution context

- `read-only`: no writes, installs, network mutations, or local state changes.
- `mutating`: writes files, installs packages, starts services, changes state.
- `destructive`: deletes data, drops databases, force-pushes, etc.

Use `--scope project` (default; shared and committed) unless the command is
machine-specific, then `--scope personal`. If the command needs a specific
directory, environment, or postcondition, register first and then edit the
generated YAML to add `working_dir`, `env_vars`, `preconditions`, or `verify`
(see `schemas/procedure.schema.json`). Never store secrets in `env_vars`.

### 5. Register with the CLI

The command is **positional**; there is no `--command` flag:

```bash
treble-add "<exact command>" \
  --name <slug> \
  --description "<routing-friendly description>" \
  --risk read-only|mutating|destructive \
  [--alias <alias>]... \
  [--scope project|personal] \
  [--overwrite]
```

`treble add ...` is the same implementation. Use `--overwrite` only when the
user clearly wants to replace an existing procedure. If you need fields the
CLI does not expose (`working_dir`, `verify`, `preconditions`), edit the
generated YAML and validate it with `treble show <slug>`.

#### Updating an existing procedure

There is no alias-only command. To add an alias, read the current definition
with `treble show <name>`, then re-register with the same command, name,
description, risk, scope, **all existing aliases**, plus the new alias, and
`--overwrite`.

### 6. Verify before telling the user

```bash
treble list
treble show <slug>
treble explain <slug>      # exact argv, working directory, risk
treble --dry-run <slug>    # preview without executing
treble test <slug>         # deterministic by-name run, only when safe
```

Confirm the argv, risk, scope, and working directory. Do not run a
mutating/destructive command just to verify it; use `explain` and
`--dry-run`. For read-only commands, `treble test` is appropriate.

### 7. Tell the user how to invoke it

Report:

- the canonical name: `treble <slug>`;
- any aliases: `treble <alias>`;
- a natural-language example: `treble "run the weekly report"` (free-form
  routing needs the decision service);
- `treble test <slug>` for deterministic/CI use;
- the declared risk and whether it will prompt before running.

### Worked examples

**Read-only test command**

```bash
treble-add "python -m pytest tests/unit/test_cli.py -q" \
  --name test-cli \
  --description "Run the focused CLI unit tests with pytest; use for 'run cli tests' or 'test the cli'." \
  --alias cli-tests \
  --risk read-only
```

**Mutating build command**

```bash
treble-add "pnpm run build" \
  --name build \
  --description "Build the project with pnpm; use for 'build the app' or 'compile the frontend'." \
  --risk mutating
```

**Existing procedure + new alias**

```bash
treble show check-no-verify            # copy its command, description, aliases
treble-add "<same command>" --name check-no-verify \
  --description "<same description>" --risk read-only \
  --alias check-fast --alias verify-check --overwrite
```

### MCP note

The `treble-mcp` server exposes `list_procedures`, `show_procedure`,
`explain_procedure`, `run`, `test`, `remove`, and `stats`. It does **not**
expose an add/register tool. If the agent has shell access, use `treble-add`
as above. If it does not, give the human the exact `treble-add` command.
`treble "add ..."` only returns a hint; it does not register. A mutating tool
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
