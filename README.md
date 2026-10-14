# Treble — A Decision-Driven Command Execution Harness

**Status:** Implemented MVP — Milestones 1–2 complete, Milestone 5 half-complete, Milestones 3–4 pending (see §10)
**Working name:** Treble
**Primary implementation language:** Python (requires ≥ 3.11)
**Runtime dependency:** the local Von decision-model server (open-source
`von` weights served over `http://127.0.0.1:8765/v1/systemone`); Treble fails
closed when Von is unreachable
**Core principle:** Deterministic execution, decision-model routing, LLM-assisted exception handling.

## 1. Overview

Treble is a lightweight command execution harness that allows developers to invoke familiar development commands without needing to remember environment-specific flags, permission requirements, execution procedures or workarounds.

Rather than executing every command exactly as typed, Treble maintains a registry of known commands and their validated execution procedures. A decision model selects the appropriate procedure based on the user's request, project context and available environment information.

When a request cannot be resolved using existing procedures, Treble can delegate interpretation or procedure authoring to an LLM. Newly generated procedures are validated and reviewed before they become available for routine execution.

The goal is to reduce repetitive command-line friction while maintaining predictable, auditable and reproducible execution.

### Example

A developer normally runs:

```bash
pnpm run check
```

However, their local environment requires a particular flag or permission configuration. Another developer may not need that workaround.

Instead of remembering the appropriate invocation, the developer registers it once:

```bash
treble-add "pnpm run check --no-verify" \
  --name check-no-verify \
  --description "Run project checks without verification"
```

The exact argument placement and forwarding behaviour must be preserved by the registration implementation.

Subsequently, the developer can run:

```bash
treble pnpm run check
```

or express a more specific intent:

```bash
treble pnpm run check without verification
```

Treble resolves the request against its registered procedures and selects the appropriate execution path.

If the intent is ambiguous, Treble asks for clarification rather than
silently choosing a potentially destructive or incorrect command — or fails
closed if the decision service is unreachable.

### 1.1 Implementation status

The sections below describe the target product. What is **currently built**
(the "implemented MVP"):

- **Python CLI** (`treble`, `treble-add`) with literal sub-commands
  (`list`, `show NAME`, `explain NAME`, `test NAME`, `remove NAME`, `add`)
  and dynamic dispatch.
- **YAML procedure registry** in `./.treble/procedures/` (project) and
  `~/.treble/procedures/` (personal), validated against a JSON Schema.
  Procedures carry names, aliases, descriptions, command vectors, risk,
  scope, and verification rules. Names/aliases may not start with `-`.
- **Von-first routing** (Milestone 2): every free-form request runs through
  the decision model — run gate (Noul) + target/control Choices — with
  confidence/margin gates that clarify rather than guess, a Noul
  "showdown" confirmation for near-tied picks, an exact-name collision
  resolution for near-duplicate names, an inspect-precedence signal that
  routes leading show/explain/list/what/how phrases to the control plane,
  a mutating/destructive confirmation
  gate that always prompts before touching the registry or running a mutating
  procedure, and fail-closed behaviour when Von is down.
- **Argument forwarding** (deterministic, §5 Layer 1): calling a registered
  name/alias/command with trailing flags runs the stored argv plus those
  flags, with no model call.
- **Positional flag ownership**: flags before the identifier are Treble's
  (`--dry-run`, `--yes`); everything after belongs to the command.
- **Safe runtime**: no shell interpolation, risk-gated confirmation,
  timeouts, post-execution verification, redacted JSONL audit and outcome
  logs, and actionable failure messages (missing executable, ENOENT).
- **Usage logging & `treble stats`**: every routed request is appended to a
  project-local `.treble/events.jsonl` and every execution to
  `.treble/audit.jsonl` (each carrying the invocation `source` and, for runs,
  the routing decision). `treble stats` (or `--json`) summarizes requests,
  routing distribution, first-try success, latency, hot and unused procedures.
- **Test/eval harness**: `pytest` (unit + integration),
  `scripts/smoke_test.sh` (end-to-end CLI), and a 73-case confusion-matrix
  eval suite (`evals/run_eval.py`) with per-category breakdown, a safety
  property that includes *unrequested execution* (running when the user asked
  only to inspect), a determinism/variance check (`--repeat`), JSONL result
  capture, and A/B prompt variants; see `EVALUATION.md` for the measured runs.

**Not yet built** (deferred): LLM-assisted procedure authoring (Layer 6 is an
interface stub), team-shared registries, environment-precondition
*enforcement* (kept as utilities), daemon, marketplace, and cross-machine
sync. See §9/§10.

## 2. The problem

Development environments differ in ways that make routine operations unnecessarily difficult.

Common examples include:

- Different operating systems, shells, runtimes and package-manager versions.
- Environment-specific flags needed to run tests or builds.
- Permission prompts imposed by operating systems, terminal configurations or coding-agent sandboxes.
- Different environment variables and local configuration.
- Repeatedly rediscovering the correct test, lint, build or deployment command.
- Shell history and personal aliases that are unavailable to teammates.
- AI coding agents repeatedly rediscovering successful commands.
- Project-specific workarounds that are undocumented or difficult to reproduce.

Existing task runners help teams define standard commands. Treble addresses the additional problem of selecting the correct execution procedure when users express their intent differently or have different local requirements.

The motivating example is a team in which one developer can run `pnpm check` normally, while another repeatedly encounters permission or environment issues. Treble should make the successful procedure discoverable, reusable and verifiable.

## 3. Product concept

Treble sits between the user and the command being executed.

It provides three primary capabilities:

1. **Command registration:** Record known-good command procedures, their descriptions, arguments, preconditions and verification requirements.
2. **Decision-driven execution:** Use the Von decision model to select the correct registered procedure.
3. **Exception handling:** Use an LLM to interpret unfamiliar requests, diagnose failures or propose new procedures when existing ones are insufficient.

Treble is not intended to be a general-purpose autonomous shell agent. Its default behaviour should be to select and execute a known procedure rather than generate a new shell command for every request.

## 4. Proposed user experience

### 4.1 Register a procedure

A developer registers an exact command (positional) and gives it a
human-readable description, optional aliases, scope and risk:

```bash
treble-add "pnpm run check --no-verify" \
  --name check-no-verify \
  --description "Run checks without verification"
treble-add "npm run test" \
  --name test \
  --description "Run the test suite" \
  --alias tests          # repeatable; -a tests --alias suite
# Optional: --scope project|personal, --risk read-only|mutating|destructive,
#           --overwrite to replace an existing procedure of the same name.
```

The equivalent `treble add "<command>" --name ...` exists in the `treble`
CLI. Registration captures:

- Procedure name and natural-language description.
- Exact executable and argument list (no shell-string re-parsing at run).
- Optional aliases; aliases are full alternate identifiers.
- Optional working-directory, environment and precondition metadata.
- Expected exit codes and post-execution verification checks.
- Risk level (read-only, mutating, destructive) that drives confirmation.
- Scope: personal (`~/.treble/`) or project (`./.treble/`).
- `enabled` flag (default true) for invalidation/disablement.

Names and aliases may not start with `-` (enforced at registration) so the
positional flag-ownership boundary is unambiguous.

The initial MVP supports explicit command registration. Automatically
generating procedures is deferred (Layer 6 / Milestone 4).

### 4.2 Execute a registered procedure

```bash
treble check-no-verify
```

Or use the underlying command as the entry point:

```bash
treble pnpm run check without verification
```

Resolution order: deterministic **argument forwarding** first (a registered
name/alias/command followed by trailing flags, §5 Layer 1), then **Von**
routing for everything else. If the request references one approved
procedure unambiguously, it runs subject to the safety policy. Ambiguous
requests produce a clarification listing Von's top candidates rather than a
silent choice; unrelated requests escalate.

### 4.3 Inspect and manage procedures

```bash
treble list
treble show check-no-verify
treble explain check-no-verify     # NAME (not free-form intent)
treble test check-no-verify        # run a named procedure directly, bypassing Von
treble remove check-no-verify
treble stats                       # usage summary from .treble/events.jsonl + audit.jsonl
treble  # or the natural-language equivalents, e.g. "show me the build step"
```

These commands make the registry transparent so users can inspect exactly
what will run. `treble explain NAME` prints the stored argv, working
directory, risk and verification requirements; `treble test NAME` is the
deterministic by-name execution path.

Destructive operations confirm before acting on **both** paths: `treble remove
NAME` (and the free-form route) prompts before deleting, and `treble test NAME`
prompts when the procedure's declared `risk` is `mutating` or `destructive`.
Confirmation is driven by the declared risk, not by inspecting the command
text — a procedure registered as `read-only` runs without a prompt even if its
command is `rm -rf …`.

### 4.4 Using Treble in another repo

Treble installs once per machine and lives *inside* each repo it serves.

```bash
# install the CLI (isolated, on PATH)
pipx install git+https://github.com/OscarVGit/treble
# or: uv tool install git+https://github.com/OscarVGit/treble

cd ~/my-project
treble init                        # scaffold .treble/ + update .gitignore
treble-add "pnpm run check --no-verify" \
  --name check-no-verify --description "Run checks without verification" \
  --risk read-only
git add .treble/procedures .gitignore && git commit   # share with the team
```

- **Commit `.treble/procedures/`** — that is how a team shares known-good
  commands (project scope). Runtime state (`events.jsonl`, `audit.jsonl`,
  `outcomes.jsonl`, `von.log`) is gitignored. `treble init` writes the right
  `.gitignore` entries for you.
- **No config required** — project scope resolves from the working directory.
- **Von is optional.** Without it, the deterministic paths work with no extra
  dependency: `treble list`, `treble test <name>`, `treble <name> --flag`
  (forwarding), `treble stats`, `treble-add`. Only free-form routing
  (`treble "run the checks"`) needs the decision service — start it with
  `scripts/run_von.sh`, or `pip install "treble[von]"` and `von serve`.
- **Run `treble doctor`** to check the install, the Von endpoint and the
  registry.

**From JavaScript / `package.json`.** A Python tool can't self-contain through
npm, but npm scripts can call the installed CLI. Register procedures once, then
wire them into `package.json`:

```json
{
  "scripts": {
    "check": "treble test check-no-verify",
    "build": "treble test build",
    "treble:list": "treble list",
    "treble:stats": "treble stats"
  }
}
```

Because these call `treble test <name>` (deterministic), they run in CI without
Von. For an agent, add the paragraph from `AGENTS.md` so it prefers the registry
over re-deriving flags.

## 5. Architecture

Treble should follow a deterministic-first architecture.

### Layer 1 — CLI and request parsing

Receives the user's input, current working directory and relevant project metadata.

Inputs may include:

- Exact command names.
- Registered procedure identifiers.
- Natural-language descriptions.
- Explicit execution constraints.

The CLI should distinguish shell arguments from Treble's own arguments and avoid relying on ambiguous shell-string parsing.

**Dispatch rule.** A sub-command runs deterministically only when the
invocation fits its literal grammar (`treble list`, `treble show NAME`,
`treble remove NAME`, `treble test NAME`, `treble add --name ...`). Anything
else — extra words, unknown options, or a natural-language phrasing that
merely starts with a sub-command word, such as `treble remove the hello
procedure` — is routed through Von as free-form intent. This keeps the
tool's own commands deterministic and cheap while ensuring that every
free-form message, including one that contains a Treble-level command, is
resolved by the decision model.

**Flag ownership is positional.** Flags *before* the procedure identifier
are Treble's; every token *after* it belongs to the command. There are no
reserved-word exceptions and no `--` escaping:

```
treble --dry-run check-no-verify        # Treble's plan, doesn't execute
treble check-no-verify --dry-run        # command's flag, forwarded verbatim
treble --yes check-no-verify --watch    # Treble auto-confirm; --watch forwarded
```

An unknown *leading* flag is an error rather than silently passed through:
`treble --watch check` fails with `unknown Treble option '--watch'; flags
for the command belong after the procedure name`. Procedure names and
aliases may not start with `-` (enforced at registration) so the
identifier boundary is unambiguous.

**Argument forwarding.** When the leading tokens exactly reproduce a
registered identifier — a name, an alias, or the procedure's full
registered command — and the first trailing token is flag-like (starts
with `-`, or is `key=value`), the request is executed deterministically
with no Von call: the registered argv runs with the remaining tokens
appended verbatim.

```
treble check-no-verify --watch     # pnpm run check --no-verify --watch
treble cnv --attach                # alias match, same result
treble pnpm run check --watch      # full command match
```

The first trailing token *not* being flag-like disables forwarding and
sends the whole request to Von — which is what keeps the natural-language
example `treble pnpm run check without verification` routing to
`check-no-verify` instead of hijacking `check` with junk arguments.

### Layer 2 — Procedure registry

Stores versioned execution procedures in a simple, inspectable format.

A procedure should contain:

- An identifier and description.
- An executable and structured argument list.
- Preconditions and environment constraints.
- Allowed side effects and permission requirements.
- Validation rules.
- Optional aliases and natural-language descriptions.
- Provenance and version information.

The registry should initially be local and project-aware. Team sharing can be introduced after the execution model is stable.

### Layer 3 — Procedure metadata (no deterministic decider)

Treble does not use deterministic matching to *decide* which procedure to
run. Every free-form request is routed through the decision model, including
exact procedure names and verbatim commands.

The single exception is **argument forwarding** (§5 Layer 1): when the
leading tokens exactly reproduce a registered identifier and the first
trailing token is flag-like, the stored argv runs with the trailing tokens
appended. That is argument passing, not procedure selection — there is no
decision to query the model for.

This layer retains procedure metadata helpers (declared preconditions such
as required executables or environment variables) as runtime utilities for
diagnostics. They do not filter the option set handed to the decision
model: availability and permission management are not Treble's job at
routing time.

### Layer 4 — Von decision model

Von routes the **ambiguous middle** of every free-form request. Around it sit
a small number of explicit, deterministic signals for forms that are
unambiguous — they select *which stage* runs, never the action itself, and
never execute anything:

- **Argument forwarding** — a registered identifier plus trailing flags runs
  the stored argv directly (§5 Layer 1).
- **Inspect precedence** — a leading inspection verb (`show`, `explain`,
  `describe`, `display`, `list`, `what`, `how`) routes to the control plane
  instead of the run gate.
- **Bare-name resolution** — a request that is *only* a registered name or
  alias routes to the run path.

Each exists because Von's Noul gate cannot separate the case by wording
(measured — `EVALUATION.md` §7–§10). In every case the model still chooses the
verb and target; the signal only picks the question. If Von is unreachable,
Treble fails closed and reports that it cannot route.

Routing is decomposed into the primitives Von is strongest at:

1. **Run gate (Noul):** is this a request to run a procedure, or to manage
   procedures (list/show/explain/test/remove/add)? The uncertain middle
   (for example a bare procedure name) defaults to run.
2. **Target selection (Choice):** for a run request, which registered
   procedure to execute.
3. **Control verb (Choice):** for a management request, which action;
   targeted actions (show/explain/test/remove) then get a further Choice
   over the procedure names.

The model chooses from a finite set of available actions — it never
produces arbitrary shell commands. Option keys are bare procedure names or
action verbs, so the model's answer maps directly onto an action without
parsing natural-language output.

A decision whose winning probability is below the confidence threshold, or
whose top two options are within the ambiguity margin, falls back to
clarification. `none-of-the-above` escalates.

**Showdown gate.** When a run-target Choice lands *within* the ambiguity
margin (a near-tie), Treble does not hard-clarify. It asks a confirmation
Noul — "does the request really refer to the top pick, not the runner-up?"
— and then acts on that answer:

- Noul confident (`p ≥ 0.6`): execute the top pick normally.
- Noul unsure (`0.3 ≤ p < 0.6`): execute the top pick, but **ask the user
  to confirm** first (naming the runner-up) so a wrong pick is caught.
- Noul rejects (`p < 0.3`): abandon to clarification.

This turns the common "two similar procedures" failure mode into a
checkable decision instead of a silent guess or a dead-end.

**Exact-name collision.** A related failure is the *confident* wrong pick:
the request names a procedure exactly (`check`) but the model prefers a longer
name that extends it (`check-no-verify`), and no near-tie fires because the
model is sure. When the leading tokens match a registered name exactly but the
model picked a longer name extending it, Treble runs the collision Noul and
keeps the longer pick only if the Noul is confident; otherwise the exact name
wins. This is registry-grounded disambiguation of an already-selected action,
not deterministic routing; on the original 24-case bank it lifted the eval from
15 to 17 (`EVALUATION.md` §4; §6 covers the expanded 70-case bank).

**Inspect precedence.** A request whose first non-filler token is an
inspection/management verb (`show`, `explain`, `describe`, `display`, `list`,
`tell`, `what`, `how`) routes straight to the control plane, bypassing the run
gate — so "show me the build procedure" inspects instead of executing. Like
argument forwarding, this is a deterministic *signal* that selects which stage
runs, not a routing decision: the model still chooses the verb and target, and
a bare procedure name (even one spelled like a verb) is never hijacked. It
exists because Von's gate cannot separate "show X" from "run X" by wording
(measured — `EVALUATION.md` §7–8), and it moved the eval's inspect category
from 2/11 to 7/11 while removing every unrequested execution (`unrequested`
7 → 0, `safe` False → True).

**Mutating confirmation gate.** Independently of confidence, any `remove`
action and any `select`/`test` of a `mutating` or `destructive` procedure is
flagged `confirm`, so the runtime always asks before changing the registry or
running a mutating procedure. This is what makes the safety property hold
even when the model is *confidently wrong* — the case the showdown cannot
catch. The safety boundary is strict: Von *selects*; the runtime *enforces*.
Mutating actions (add/remove) and any destructive procedure still pass
through the confirmation and policy gates regardless of model confidence.

### Layer 5 — Deterministic execution runtime

The runtime executes the selected procedure.

It is responsible for:

- Constructing the argument vector (stored argv plus any forwarded extras).
- Applying the intended working directory and approved environment configuration.
- Checking declared preconditions (kept as utilities; not used to filter
  the Von option set).
- Enforcing permissions and execution policies (risk-gated confirmation
  plus the showdown confirmation gate).
- Capturing stdout, stderr and exit codes.
- Applying timeouts and cancellation.
- Running post-execution verification.
- Recording a redacted, append-only audit trail.
- Reporting common failures **actionably** — a missing executable (exit
  127) suggests installing it or registering a different procedure, and an
  `ENOENT` failure points at the working directory — instead of a bare
  exit-code mismatch.

Von selects the procedure; it does not override the runtime's permission checks.

### Layer 6 — LLM escalation and procedure authoring

When the registry and decision model cannot resolve the request, an LLM may:

- Interpret a natural-language constraint.
- Explain an unfamiliar error.
- Propose diagnostic steps.
- Suggest a new procedure.
- Generate a draft registry entry or deterministic wrapper.

The LLM must not silently turn its generated proposal into an unrestricted executable command. New or materially modified procedures should be inspected, validated and approved before registration.

Once approved, the procedure should run without needing the LLM on every invocation.

### Layer 7 — Verification and learning

After execution, Treble records whether the procedure completed successfully and whether its postconditions passed.

Repeated success can improve procedure selection and help identify useful new variants. However, success alone should not automatically establish that a procedure is safe or generally applicable.

Changes to the project, runtime, permissions or dependencies may invalidate an otherwise successful procedure.

## 6. Environment compatibility

Environment compatibility is an important extension of the core product.

A registered procedure might specify that it requires:

- A particular Node.js version.
- A project-pinned package-manager version.
- A specific working directory.
- A required environment variable.
- A permission that must be granted by the host execution environment.
- A particular runtime or sandbox configuration.

Before execution, Treble can compare the current environment with those requirements.

When a procedure fails, deterministic diagnostics should classify common failures, including missing executables, incompatible runtime versions, filesystem access errors and explicit sandbox denials.

Treble should then select an approved remediation or ask for assistance.

It must not assume that all permission failures can be fixed by adding command-line flags. Operating-system permissions, shell configuration and agent sandbox policies are distinct mechanisms and need different remedies.

## 7. Safety and reliability

Command execution is inherently risky, so safety must be a core design constraint.

Treble should:

- Preserve the exact registered executable and argument list.
- Avoid constructing commands through unsafe string interpolation.
- Never interpret an untrusted registry entry as an instruction to bypass security controls.
- Require appropriate confirmation for destructive actions and elevated privileges.
- Refuse to grant broad permissions automatically.
- Redact secrets from logs and diagnostic reports.
- Keep a record of the selected procedure, applied arguments, result and verification outcome.
- Allow procedures to be disabled or invalidated.
- Make it possible to inspect the final execution plan before running it.

A successful exit code is not always proof of a successful task. Procedures should support explicit postconditions, such as expected test results or generated artifacts.

## 8. Existing projects and differentiation

Treble overlaps with several established categories of developer tooling.

**mise** manages development tools, environment variables and repeatable project tasks. It is a strong reference for project-aware execution and environment management.

Repository: https://github.com/jdx/mise

**just** provides a command runner for storing and invoking repeatable recipes. It is a useful reference for a lightweight, explicit command registry.

Repository: https://github.com/casey/just

**Shell-AI** generates shell commands from natural-language requests. It demonstrates the natural-language command-line interaction pattern.

Repository: https://github.com/ricklamers/shell-ai

**nsh (The Natural Shell)** provides an AI-powered shell assistant with terminal history, project context and natural-language interactions.

Repository: https://github.com/fluffypony/nsh

**JevHarness** explores authoring task-specific decision-model harnesses using an LLM, then freezing the resulting strategy for routine execution.

Repository: https://github.com/TianyuCodings/JevHarness

These projects establish that task runners, environment managers and AI shell interfaces already exist. Treble should not claim novelty merely because it combines a CLI with natural-language interpretation.

Its proposed differentiation is the combination of:

1. A registry of explicit, versioned execution procedures.
2. Von-based selection among known procedures.
3. Environment-aware preconditions and verification.
4. LLM-assisted creation of new procedures when needed.
5. Safe, auditable execution that does not require an LLM for every run.
6. Optional sharing of verified procedures across a team.

The central product question is whether this combination is materially more useful than a conventional task runner plus a shell assistant.

## 9. MVP scope

The initial implementation should remain deliberately small.

### Include

- Python CLI (`treble`, `treble-add`).
- Local YAML procedure registry (directory-based, JSON-Schema validated).
- Exact command registration with aliases, scope, risk and verify rules.
- Deterministic execution paths: literal sub-commands and argument
  forwarding of trailing flags onto a registered command.
- Positional flag ownership (`--dry-run`/`--yes` before the identifier).
- Natural-language routing through von (run gate + target/control Choices).
- Structured execution, exit-code reporting and post-execution verification.
- A dry-run / explain mode for inspecting the execution plan.
- Safe handling of ambiguous requests (clarification) and fail-closed
  behaviour when the decision service is unreachable.
- A basic LLM fallback *interface* that proposes changes rather than
  automatically applying them (not yet wired; Milestone 4).
- An evaluation suite (`evals/run_eval.py`) and CLI smoke harness
  (`scripts/smoke_test.sh`).

### Defer

- Automatic system permission changes.
- A background daemon.
- Cross-machine environment synchronisation.
- A hosted procedure marketplace.
- Automatic conversion of arbitrary shell history into procedures.
- Autonomous execution of generated shell commands.
- Complex workflow graphs and multi-agent orchestration.
- Broad support for every operating system and shell.

These features should be considered only after the core routing and execution model has demonstrated value.

## 10. Proposed development milestones

Current standing:

| # | Milestone | Status |
| --- | --- | --- |
| 1 | Deterministic command registry | Complete |
| 2 | Decision-model routing | Complete |
| 3 | Environment preconditions | Not started — fields captured, not enforced |
| 4 | LLM-assisted procedure authoring | Not started — Layer 6 is an interface stub |
| 5 | Evaluation and team sharing | Partial — evaluation suite built; shareable registries pending |

Milestones 1 and 2 are complete; Milestone 5's evaluation half is built
(`evals/run_eval.py`, `EVALUATION.md`); Milestones 3 and 4 are untouched.

### Milestone 1 — Deterministic command registry

Implement registration, listing, inspection and execution of named procedures.

Success criterion: users can register a command once and execute it repeatedly without changing its arguments or behaviour.

### Milestone 2 — Decision-model routing

Route every free-form request through the decision model over a finite
action space that spans procedure execution and the control plane
(list/show/explain/test/remove/add).

Success criterion: Von reliably chooses the intended action and target
among procedures and control-plane operations, asks for clarification when
the intent is ambiguous, and fails closed when the decision service is
unreachable.

### Milestone 3 — Environment preconditions

Capture runtime versions, working-directory constraints and relevant configuration. Add safe diagnostics for common failures.

Success criterion: Treble can identify when a registered procedure's preconditions do not hold instead of blindly retrying it.

### Milestone 4 — LLM-assisted procedure authoring

Allow an LLM to propose a new procedure when the existing registry is insufficient.

Success criterion: the generated procedure can be reviewed, tested and approved before subsequent execution becomes deterministic.

### Milestone 5 — Evaluation and team sharing

The evaluation suite is built (`evals/run_eval.py`; results in
`EVALUATION.md`). The remaining work is project-local and shareable procedure
registries.

Success criterion: demonstrate reduced command-entry friction and successful reuse without increasing incorrect or unsafe execution.

## 11. Evaluation strategy

Treble should be compared against simple alternatives, rather than evaluated only through demonstrations.

The measured runs — a 70-case bank, per-category breakdown, a safety property
that folds in *unrequested execution*, a determinism/variance check, and two
falsified prompt A/Bs — are written up in `EVALUATION.md`. The metrics below
are what `evals/run_eval.py` reports.

Useful baselines include:

- Manual shell commands.
- Shell aliases or scripts.
- A conventional task runner.
- Natural-language command generation using an LLM.
- Deterministic matching without a decision model.
- Von-based routing with an LLM fallback.

Measure:

- Correct procedure selection rate.
- Command execution success rate.
- Ambiguous-request handling.
- Number of unnecessary model calls.
- End-to-end latency and model cost.
- Time saved over repeated invocations.
- Procedure invalidation and stale-configuration detection.
- Incorrect or unsafe execution attempts.

A particularly useful benchmark would contain commands with multiple variants, similar natural-language descriptions, changing environment conditions and deliberately ambiguous requests.

The objective is not to maximise the percentage of requests routed without an LLM at any cost. It is to maximise verified task completion while keeping execution predictable, secure and economical.

## 12. Long-term direction

If the MVP succeeds, Treble could evolve from a command registry into a general-purpose compatibility layer for developer workflows.

A team could share validated procedures for testing, linting, building, database migrations, deployment checks and other repetitive tasks. Treble could select the correct procedure based on the user's intent and environment, while an LLM handles exceptions and proposes new workflows.

Over time, the system could accumulate reusable procedural knowledge without requiring every execution to repeat the original reasoning process.

The long-term vision is straightforward:

**Describe what you want to do. Treble selects a known-good procedure, executes it under explicit constraints, verifies the result and learns how to handle future variations.**

### Possible extension — beyond developer CLIs

The registry and decision layer are **transport-agnostic**: a procedure is just
a named action with a description, a command vector and a declared risk.
Nothing in the routing model assumes the backend is a shell command. That opens
a possible direction — the same natural-language front-end for **non-technical
users**: "generate the monthly sales report" mapping to a registered VBA macro,
"open the timesheet" to an app launch, "back up my documents" to a script.

This is a product direction, not current scope, and it is mostly work *past*
the milestones in §10:

- **Pluggable action kinds** (small): an `action` field so a procedure can be a
  shell command, an AppleScript, an app launch, a URL or a macro wrapper,
  instead of implicitly a shell command. (The macro case already works today
  via a registered wrapper script; the field would make it first-class.)
- **A non-terminal front-end** (large): a tray app, desktop shortcut, search
  box or chat surface. The routing is ready; the *delivery surface* is not.
- **An authoring flow** — leans on Milestone 4, so a non-technical user (or
  their admin) never hand-writes YAML.
- **Preconditions and verification** — leans on Milestone 3, so "Excel is not
  running" or "the macro failed" is reported rather than blindly retried.
- **Distribution** — an installer rather than `pip install`.

Two ideas to keep separate:

- **On-demand actions** (macro, app launch) fit Treble's interactive, one-shot
  model directly.
- **Scheduled / startup execution** is a *different* component — a daemon or
  scheduler, deferred in §9 — that would consume the same registry, not extend
  the CLI.

The risk posture also shifts. This audience needs *more* guardrails, not more
flexibility: narrow action spaces, confirmation-before-execute and
clarify-don't-guess are exactly what the decision layer already provides — but
the declared-risk trust model matters far more, and "register an action that can
do anything" becomes a governance question (who approves a procedure?).

The smallest validating step: make the backend pluggable while keeping the CLI,
and demonstrate one non-shell action end to end.

The first objective is more modest: build a reliable command registry with deterministic execution, then establish whether Von-based routing and LLM-assisted procedure creation improve it enough to justify their complexity.
