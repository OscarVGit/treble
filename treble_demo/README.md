# Treble Demo — The Old Way vs. The Treble Way

A self-contained, mock-only demo built for a side-by-side screenshot or video.
Nothing here touches Excel, a real workbook, or an external service. The Python
runner validates the legacy flag surface and prints a realistic execution log.

## What's in here

| Path | Purpose |
| --- | --- |
| `scripts/run_vba_macro.py` | Mock Excel/VBA runner. Requires five flags and prints a weekly-report log. |
| `scripts/old_way.sh` | The long, manual invocation (paths + flags + env clutter). |
| `config/weekly_report.json` | Mock workbook/report configuration used by the runner. |
| `.treble/procedures/run-thursday-vba.yaml` | The Treble registry entry for the runner. |

Treble uses a directory-based YAML registry, **not** a single `registry.json`.
The equivalent registry file for this demo is
`.treble/procedures/run-thursday-vba.yaml`.

## 1. Start the local model server (`von serve`)

Free-form routing needs a `/v1/systemone` server. If you already have the
`treble-distill` checkout, serve its fine-tuned `checkpoints/von-ft`
(the treble-400m model) directly:

```bash
# terminal A
cd "$HOME/Desktop/treble-distill"
VON_BIN="$HOME/Desktop/Von/.venv/bin/von" ./scripts/serve.sh
```

`serve.sh` listens on `127.0.0.1:8765` and defaults
`VON_CHECKPOINT_DIR` to `checkpoints/von-ft`. If your `von` binary lives
elsewhere, adjust `VON_BIN`. The equivalent direct command is:

```bash
VON_CHECKPOINT_DIR="$HOME/Desktop/treble-distill/checkpoints/von-ft" \
  von serve --host 127.0.0.1 --port 8765
```

Then, in the shell where you will run Treble:

```bash
export TREBLE_DECISION_URL="http://127.0.0.1:8765/v1/systemone"
```

Fallback: if you do not have `treble-distill`, download the checkpoint and the
server from the Treble repo root:

```bash
./scripts/setup-model.sh --with-von
```

That installs `von-sdk` into `$HOME/.treble/venvs/von` (Python >= 3.12) and
downloads the checkpoint to `$HOME/.treble/models/treble-400m`. If you already
have a Von venv (for example `$HOME/Desktop/Von/.venv`), reuse it instead of
creating another one:

```bash
VON_VENV="$HOME/Desktop/Von/.venv" ./scripts/setup-model.sh --with-von
```

Then serve (replace `VON_VENV` if you reused an existing venv):

```bash
VON_VENV="${VON_VENV:-$HOME/.treble/venvs/von}"
VON_CHECKPOINT_DIR="$HOME/.treble/models/treble-400m" \
  "$VON_VENV/bin/von" serve --host 127.0.0.1 --port 8765
```

Verify the server is up with:

```bash
curl -fsS http://127.0.0.1:8765/health && echo " von is up"
```

## 2. The Old Way (type the full command)

For the negative half of the demo, show this command and type or paste all of
it — don't hide it behind a wrapper. Five flags, three paths, an ISO date, and
a macro name you have to remember:

```bash
cd treble_demo

TZ="America/New_York" \
VBA_REPORT_PROFILE="weekly-report-production" \
VBA_LOG_LEVEL="DEBUG" \
python3 ./scripts/run_vba_macro.py \
  --config-path ./config/weekly_report.json \
  --target-date 2026-11-05 \
  --macro-name ThursdayWeeklyReport \
  --output-dir ./output/2026/11/05/thursday-weekly-report \
  --verbose
```

`scripts/old_way.sh` contains this exact command if you want a copy-paste card
or a runnable version.

Missing or wrong flags produce standard errors, which is a good live beat:

```bash
# Forget --output-dir and --verbose:
python3 ./scripts/run_vba_macro.py \
  --config-path ./config/weekly_report.json \
  --target-date 2026-11-05 \
  --macro-name ThursdayWeeklyReport
# run_vba_macro.py: error: the following arguments are required: --output-dir, --verbose
```

Or mistype `--target-date` as `--target_date` (underscore instead of hyphen):

```bash
python3 ./scripts/run_vba_macro.py \
  --config-path ./config/weekly_report.json \
  --target_date 2026-11-05 \
  --macro-name ThursdayWeeklyReport \
  --output-dir ./output/2026/11/05/thursday-weekly-report \
  --verbose
# usage: run_vba_macro.py [-h] --config-path FILE --target-date YYYY-MM-DD
#                         --macro-name NAME --output-dir DIR --verbose
# run_vba_macro.py: error: the following arguments are required: --target-date
```

### Suggested live-demo sequence

1. Show the full `python3 ... --verbose` command and run it. Let the flags and
   long paths fill the screen.
2. Run it once more with a missing flag or typo so the friction is visible.
3. Switch to the Treble Way below: `treble "run thursday vba"`.

## 3. The Treble Way

```bash
cd treble_demo
treble "run thursday vba"
```

The same procedure, with every path, flag, date, and macro name already in the
registry. All of these route to it too:

```bash
treble "execute weekly report macro"
treble "run thursda vba macro"     # misspelled on purpose
treble run thursday vba            # unquoted form
```

If `treble` is not on `PATH`, use the repo venv from inside `treble_demo`:

```bash
../.venv/bin/treble "run thursday vba"
```

### Deterministic (no model server required)

```bash
treble list                        # show the registered procedure
treble explain run-thursday-vba    # print the exact argv and working directory
treble test run-thursday-vba       # run by name, bypassing the model
```

### Expected ending

Both sides finish with the same success line:

```text
[SUCCESS] Macro 'ThursdayWeeklyReport' executed in 1.4s
```

## Notes

- The runner is **read-only**: it prints a simulated log and does not write to
  `output/`. That keeps the demo safe to run anywhere and is why the registry
  entry is marked `risk: read-only`.
- Treble writes routing state (`.treble/events.jsonl`, `.treble/audit.jsonl`)
  after a run. That is local demo state, not part of the registry.
- Run everything from `treble_demo/`; the registry entry uses `working_dir: .`
  and paths relative to that directory.
