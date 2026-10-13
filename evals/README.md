# Treble evaluation suite

Measures how well the decision model routes requests, with a confusion
matrix, a safety property, and JSONL capture for regression diffing.

Scenarios live in `scenarios/*.yaml`. Each case declares:

- `intent`: the raw tokens a user typed.
- `procedures`: a fixture registry.
- `expect`: one of `select:<name>`, `remove:<name>`, `show:<name>`,
  `test:<name>`, `explain:<name>`, `list`, `add`, `clarify`, `escalate`.
- `mutating` (optional): `true` when a wrong execution is dangerous; feeds
  the safety metric.

## Run

```bash
# Live Von server (default; honours TREBLE_VON_URL):
python evals/run_eval.py evals/scenarios/routing.yaml

# Offline, scripted model (validates harness plumbing, not the model):
python evals/run_eval.py evals/scenarios/routing.yaml --fake

# A/B a prompt variant, capturing results for comparison:
python evals/run_eval.py evals/scenarios/routing.yaml --variant default \
    --results evals/results/default.jsonl
python evals/run_eval.py evals/scenarios/routing.yaml --variant compact-gate \
    --results evals/results/compact-gate.jsonl
```

## Report

Per case, the harness classifies the outcome into one of four buckets:

| bucket       | meaning                                                   |
| ------------ | --------------------------------------------------------- |
| `correct`    | action (and target) matches the expectation               |
| `clarified`  | the system asked (CLARIFY) instead of acting              |
| `escalated`  | the system punted (ESCALATE) instead of acting            |
| `wrong`      | the system acted on something other than the expectation  |

Derived metrics:

- **safe** — no `wrong` case on a `mutating: true` procedure. This is the
  hard requirement; a single mutating wrong-pick flips it to `False`.
- **actionable** — no case silently executed the wrong thing (`wrong` = 0).
  Clarify/escalate are acceptable answers; guessing is not.
- **model_calls** — total Noul/Choice calls made across the suite.
- **avg_latency_ms** — mean routing latency per case.

Exit codes: `0` pass, `1` on model error (e.g. Von unreachable), `2` on any
`wrong` case (CI gate).

## Results capture

`--results <path>` appends one JSON object per case: `{variant, case,
expected, got, classification, safe, probabilities, latency_ms, model_calls,
result, error}`. Record a baseline and diff subsequent runs against it.

## A/B prompt variants

`--variant` selects a prompt configuration from `decision.prompts.VARIANTS`:

- `default` — production prompts.
- `compact-gate` — replaces the verbose run-gate Noul instruction with a
  short classifier line and moves the "bare name = run" rule into the state
  as a framing line. Hypothesis: shorter instruction, better gate.

A variant is a hypothesis, not a tweak. Compare the JSONL captures side by
side; see `EVALUATION.md` for the measured outcome of the first A/B.

## Scenario bank

`scenarios/routing.yaml` currently holds 24 cases across categories: bare
names, verbatim commands, natural-language run/inspect/test/list/add,
remove (mutating), destructive phrasing, out-of-domain, and edge cases
(empty registry, single procedure, alias, long context). Add cases by
category; mark `mutating: true` wherever a wrong pick is dangerous.

Deterministic paths (literal sub-commands, argument forwarding) intentionally
bypass the model and are covered end-to-end by `scripts/smoke_test.sh` — this
suite measures the *model* path only.
