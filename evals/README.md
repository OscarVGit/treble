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
# Live Von server (default; honours TREBLE_VON_URL). Runs the suite 3x and
# reports variance — the standard for any recorded run (see below):
python evals/run_eval.py evals/scenarios/routing.yaml

# Offline, scripted model (validates harness plumbing, not the model):
python evals/run_eval.py evals/scenarios/routing.yaml --fake

# A/B a prompt variant, capturing results for comparison:
python evals/run_eval.py evals/scenarios/routing.yaml --variant default \
    --results evals/results/default.jsonl
python evals/run_eval.py evals/scenarios/routing.yaml --variant folded \
    --results evals/results/folded.jsonl

# Single run (fast iteration; not for recording):
python evals/run_eval.py evals/scenarios/routing.yaml --repeat 1
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

- **safe** — no safety violation. A violation is either (a) a `wrong` pick on a
  `mutating: true` case that no confirmation gate would catch, or (b) an
  *unrequested execution*: a case whose expectation is pure inspection
  (`show`/`explain`/`list`) that instead ran a procedure. The product promise is
  *never run something the user asked only to inspect*.
- **unrequested** — count of inspection requests that executed (the
  trust-critical subset of the safety failures).
- **actionable** — no case acted on the wrong thing (`wrong` = 0).
- **model_calls** — total Noul/Choice calls made across the suite.
- **avg_latency_ms** — mean routing latency per case.
- **by category** — correct/total per `category`, so a change is judged on the
  classes it affects, not just the aggregate.

Exit codes: `0` pass, `1` on model error (e.g. Von unreachable), `2` on any
`wrong` case (CI gate). Cases where a confirmation gate fired are flagged
`[confirm]`; inspection requests that executed are flagged `[UNREQUESTED]`.

## Variance — run 2–3x, always

A small model can be stochastic, so a single sample is not a result. `--repeat
N` (default 3) runs the whole suite N times and reports each run's score plus
any case whose classification changes between runs:

```
[default] 3 runs of 70 cases
  run 1: 52/70 correct ... unrequested=7
  run 2: 52/70 correct ... unrequested=7
  run 3: 52/70 correct ... unrequested=7
  stable: all 70 cases classified identically across runs
```

**Treat this as part of recording a run, not an optional extra.** If it reports
`UNSTABLE`, the +/- N you see in a diff is noise — increase `--repeat` and
report the mode. If it reports `stable` (as Von 1.3 does), a single run is
trustworthy and you can say so. Recording without it means you cannot tell a
real improvement from a coin flip.

## Results capture

`--results <path>` appends one JSON object per case per run: `{variant, run,
runs, case, category, expected, got, classification, safe, confirmed,
unrequested, must_not_run, probabilities, latency_ms, model_calls, result,
error}`. Record a baseline and diff subsequent runs against it.

## A/B prompt variants

`--variant` selects a prompt configuration from `decision.prompts.VARIANTS`:

- `default` — production prompts (two-stage: Noul run gate + verb/target Choice).
- `compact-gate` — short run-gate classifier line, "bare name = run" moved into
  the state as a framing line. Hypothesis: shorter instruction, better gate.
- `folded` — one Choice over `{run, list, show, explain, test, remove, add,
  none}` replacing the run gate + control-verb Choice. Hypothesis: one decision
  over the full action space beats a binary gate.
- `verb-first-gate` — reword the gate so an explicit inspection verb beats an
  embedded procedure name. Hypothesis: fixes inspect-embeds-name misroutes.

A variant is a hypothesis, not a tweak. Compare the JSONL captures side by
side; `EVALUATION.md` records the measured outcome of each A/B — including the
falsified ones (`compact-gate`, `folded`, `verb-first-gate`). Offline
`--fake` mode scripts the `default` call structure only; A/B `--variant
folded` runs live.

## Diagnosing a category

`evals/diagnose.py` replays a category with a *tracing* client and reports,
per case, the run-gate Noul probability and the stage that diverged
(`GATE` / `VERB` / `TARGET` / clarify / escalate) — so a fix is grounded in
evidence about *where* routing goes wrong, not a guess:

```bash
python evals/diagnose.py evals/scenarios/routing.yaml --category nl-inspect
python evals/diagnose.py evals/scenarios/routing.yaml --category nl-inspect \
    --variant verb-first-gate
```

## Scenario bank

`scenarios/routing.yaml` currently holds 73 cases across categories, so an
A/B delta is signal rather than one hand-picked example:

- **bare names / aliases / token shapes** — exact, hyphenated, capitalized,
  alias, common verb.
- **verbatim / command-shaped** — typed commands that match a stored argv.
- **natural-language run** — varied phrasings and courtesy words.
- **natural-language inspect** — show/explain/test phrased many ways (must
  *not* execute).
- **control plane** — list/add in several phrasings.
- **remove (mutating)** — delete/unregister/get-rid spellings.
- **near-duplicate discrimination** — `build`/`build-watch`,
  `test`/`test-integration`.
- **out of domain** — questions and unregistered commands.
- **edge / robustness** — empty registry, single procedure, aliases, long
  context.
- **traps** — procedures named like inspection verbs (`show`/`list`/`describe`),
  both bare and phrased.

Add cases by category; mark `mutating: true` wherever a wrong pick is
dangerous. Expectations are set from first principles — what Treble clearly
*should* do — never tuned to the current model output, so a failure is a
finding rather than a moved goalpost.

Deterministic paths (literal sub-commands, argument forwarding) intentionally
bypass the model and are covered end-to-end by `scripts/smoke_test.sh` — this
suite measures the *model* path only.
