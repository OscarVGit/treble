# Treble evaluation suite

Milestone 5 groundwork (README §11). The harness runs declarative routing
scenarios against a fixture registry and reports selection accuracy.

Scenarios live in `scenarios/*.yaml`. Each case declares:

- `intent`: the raw tokens a user typed.
- `procedures`: the fixture registry.
- `expect`: one of `select:<name>`, `remove:<name>`, `show:<name>`,
  `test:<name>`, `explain:<name>`, `list`, `add`, `clarify`, `escalate`.

Run:

```bash
# Against a live Von server (default; honours TREBLE_VON_URL):
python evals/run_eval.py evals/scenarios/routing.yaml

# Offline, with a scripted model:
python evals/run_eval.py evals/scenarios/routing.yaml --fake
```

## Current baseline (Von 1.3, 395M, local MPS)

**Live: 4/6. Scripted: 6/6.** The two live misses share one root cause: the
model cannot reliably discriminate procedures whose names/descriptions share
a prefix (`check` vs `check-no-verify`), and it responds to those requests
with a safe `clarify` rather than executing the wrong variant:

- `select-no-verify-variant` ("pnpm run check without verification") →
  clarify between `check` and `check-no-verify`.
- `remove-procedure` ("remove the check procedure") → clarify between the
  same two.

These are the "similar natural-language descriptions / ambiguous requests"
cases the eval exists to measure (README §11). Both fail safe: no wrong
command executes, and a mutating clarification can be confirmed by a human.

Reliable behaviors in the current build: bare unique names route to the
correct procedure (name embedded in the target option text); explicit
management verbs (list/show/remove/add) classify at ~0.95+; unrelated
requests escalate. When the run gate or the target Choice is at the
discrimination boundary, Treble clarifies rather than guessing.

Likely levers to raise the baseline: richer procedure descriptions with
alias phrases, a Noul confirmation gate before executing close calls, or a
larger decision model. These are Milestone 5 questions; the harness is the
measurement tool, not the fix.
