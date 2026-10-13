# Treble decision-model evaluation

First measured A/B, run against the live Von 1.3 server (395M, local MPS)
on 2026-10-13, with the 24-case scenario bank in `evals/scenarios/routing.yaml`.

## What the harness measures

Four-way classification per case (`correct` / `clarified` / `escalated` /
`wrong`), plus three derived properties:

- **safe** — no `wrong` classification on a `mutating: true` case. A wrong
  pick on a mutating procedure is the one outcome the system must never
  produce.
- **actionable** — no case silently executed the wrong thing. Clarifying
  and escalating are acceptable; guessing is not.
- **model_calls / avg_latency_ms** — cost and latency of the model path.

Offline (`--fake`) the scripted harness passes 24/24 — it validates plumbing
(matrix, JSONL, exit codes), not the model. Everything below is **live**.

## Baseline: `default` variant

```
15/24 correct   clarified=0  escalated=1  wrong=8  error=0
safe=False  actionable=False  model_calls=55  avg_latency_ms=129.1
```

## A/B: `compact-gate` variant

**Hypothesis.** The default run-gate Noul instruction is multi-clause
policy prose — Von's weakest tier per its own model card. Replacing it
with a short classifier line ("Is this a request to run a registered
procedure?") and moving the "bare name = run" rule into the state as a
framing line should improve gate accuracy.

```
13/24 correct   clarified=0  escalated=1  wrong=10  error=0
safe=False  actionable=False  model_calls=51  avg_latency_ms=106.1
```

**Outcome: the hypothesis is falsified.** Shorter gate instructions made
routing measurably *worse* (−2 correct, +2 wrong), and `safe`/`actionable`
stayed `False` for both. The verbose condition is load-bearing: its explicit
rule ("a bare word that names a procedure counts as run") is doing real work
for the gate, even if it's stylistically ugly. We keep `default` in
production and keep `compact-gate` as the recorded counterexample — which is
the point of measuring instead of guessing.

## What the matrix shows about the model

The 8 `wrong` cases cluster into three model limitations, all consistent
with the model card's "short, well-posed decisions" caveat:

1. **Prefix-shared names** (`check` vs `check-no-verify`). The model picks
   the longer, more "command-flavoured" name regardless of intent
   (`bare-name-near-duplicate`, `remove-named`,
   `remove-near-duplicate-must-clarify`). Notably these were confident wrong
   picks — the showdown gate (near-tie margin) did not fire because the
   model was *not* near-tied; it was confidently wrong.
2. **Natural-language inspection runs instead of inspecting** ("show me the
   build procedure", "what does the build do", "test the build procedure").
   All routed to `select` instead of `show`/`explain`/`test`. The run-gate
   biases toward execution (by design — the dominant convention for a
   command harness), and the control-verb stage misclassifies some of these.
3. **Control-verb mispicks** ("what is in the registry" → `show` instead of
   `list`; "now" → `show` instead of `escalate`).

The `clarified` bucket stayed empty in this run — the model is *decisive*,
which is precisely why `safe=False`: decisiveness without discrimination is
how wrong mutating commands get executed.

## How the safety rails performed

- **Argument forwarding** and literal sub-commands cover 100% of their
  deterministic cases (28/28 in `scripts/smoke_test.sh`) — the model is
  never consulted on those paths.
- The **showdown Noul** gate exists exactly for the near-tie case, but this
  scenario bank shows the harder failure is the *confident* wrong pick,
  which the showdown can't see. That suggests the next lever is a second
  confirmation Noul on any mutating selection, not a tighter tie threshold.

## Next levers, ranked by expected value

1. A **mutating-action confirmation Noul** (or plain confirmation prompt)
   on any `remove`/destructive selection, so `safe` can be forced to `True`
   regardless of discrimination quality.
2. **Option-text priming for inspection**: `show`/`explain`/`test` option
   text that is lexically distinct from `select`, so NL-inspect stops
   defaulting to `select`.
3. **Distinctive descriptions at registration** — the near-duplicate class
   is created by humans writing near-identical descriptions; the eval now
   quantifies its cost.
4. **A larger decision model** — the structural fix for prefix-shared
   discrimination, kept as the documented escape hatch rather than the plan.

## How to reproduce

```bash
python evals/run_eval.py evals/scenarios/routing.yaml --results /tmp/default.jsonl
python evals/run_eval.py evals/scenarios/routing.yaml \
    --variant compact-gate --results /tmp/compact.jsonl
```
