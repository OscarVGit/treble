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

**Live: 5/6. Scripted: 6/6.** The one live miss is the case this suite
exists to measure (README §11: "similar natural-language descriptions"):

- `remove-procedure` (`remove the check procedure`): with suffix-overlapping
  names (`check` vs `check-no-verify`), the model confidently picks the wrong
  variant (0.65 vs 0.16 — outside the ambiguity margin, so no clarification
  is triggered). Fails safe at the runtime boundary: remove requires
  interactive confirmation, where a human catches the mismatch.

Routing decisions that previously drove clarification on near-duplicate
procedure names are resolved by (a) a registry-grounded run gate biased
toward run, and (b) procedure names embedded in the run-target option text,
so a bare name like `hello` wins decisively over a verbose neighbour. On
rounds where the top two options land within the 0.08 ambiguity margin the
pipeline still clarifies rather than guessing.

Likely levers to raise the baseline: richer procedure descriptions with
alias phrases, a Noul confirmation gate before executing close calls, or a
larger decision model. These are Milestone 5 questions; the harness is the
measurement tool, not the fix.
