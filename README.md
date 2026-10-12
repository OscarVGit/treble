# Treble — A Decision-Driven Command Execution Harness

**Status:** Project proposal / MVP specification
**Working name:** Treble
**Primary implementation language:** Python
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

If the intent is ambiguous, Treble should ask for clarification rather than silently choose a potentially destructive or incorrect command.

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

A developer registers an exact command and gives it a human-readable description.

```bash
treble-add \
  --name check-no-verify \
  --command "pnpm run check --no-verify" \
  --description "Run checks without verification"
```

Registration should capture:

- Procedure name and natural-language description.
- Exact executable and argument list.
- Working-directory requirements.
- Environment and runtime preconditions.
- Optional environment variables, excluding secret values from stored metadata.
- Expected exit codes and verification checks.
- Whether the procedure is read-only, mutating or potentially destructive.
- Scope: personal, project-local or team-shared.
- Version and invalidation conditions.

The initial MVP should support explicit command registration. Automatically generating procedures can follow later.

### 4.2 Execute a registered procedure

```bash
treble check-no-verify
```

Or use the underlying command as the entry point:

```bash
treble pnpm run check without verification
```

The second example requires semantic resolution. Treble identifies the underlying command, interprets the additional constraint and selects the matching registered procedure.

If the request matches exactly one approved procedure, Treble can execute it directly, subject to its configured safety policy.

If several procedures match, it should ask the user to choose.

If none match, it should explain that it does not have a suitable registered procedure.

### 4.3 Inspect and manage procedures

```bash
treble list
treble show check-no-verify
treble explain "pnpm run check without verification"
treble test check-no-verify
treble remove check-no-verify
```

These commands should make the registry transparent and allow users to inspect what will actually run.

`treble explain` is particularly important: users should be able to see why a procedure was selected, which conditions matched and which flags will be applied.

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

This layer retains procedure metadata helpers (declared preconditions such
as required executables or environment variables) as runtime utilities for
diagnostics. They do not filter the option set handed to the decision
model: availability and permission management are not Treble's job at
routing time.

### Layer 4 — Von decision model

Von handles **every** incoming free-form request. There is no regex or
exact-match short-circuit and no deterministic fallback: if Von is
unreachable, Treble fails closed and reports that it cannot route.

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

The safety boundary is strict: Von *selects*; the runtime *enforces*.
Mutating actions (add/remove) and any destructive procedure still pass
through the confirmation and policy gates regardless of model confidence.

### Layer 5 — Deterministic execution runtime

The runtime executes the selected procedure.

It is responsible for:

- Constructing the argument vector.
- Applying the intended working directory and approved environment configuration.
- Checking preconditions.
- Enforcing permissions and execution policies.
- Capturing stdout, stderr and exit codes.
- Applying timeouts and cancellation.
- Running post-execution verification.
- Recording an audit trail.

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

- Python CLI.
- Local JSON or YAML procedure registry.
- Exact command registration.
- Named procedures and aliases.
- Deterministic command matching.
- Basic natural-language routing through Von.
- Structured command execution and exit-code reporting.
- Procedure preconditions and post-execution verification.
- A dry-run or explain mode.
- Safe handling of ambiguous requests.
- A basic LLM fallback interface that proposes changes rather than automatically applying them.

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

Build an evaluation suite, then introduce project-local and shareable procedure registries.

Success criterion: demonstrate reduced command-entry friction and successful reuse without increasing incorrect or unsafe execution.

## 11. Evaluation strategy

Treble should be compared against simple alternatives, rather than evaluated only through demonstrations.

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

The first objective is more modest: build a reliable command registry with deterministic execution, then establish whether Von-based routing and LLM-assisted procedure creation improve it enough to justify their complexity.
