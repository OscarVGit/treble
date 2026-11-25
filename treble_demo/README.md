# Treble Demo — The Old Way vs. The Treble Way

A self-contained demo for a side-by-side screenshot or video. The Python
runner is a mock: it never opens Excel or touches a real workbook. It exists to
show a flag-heavy legacy invocation next to a single natural-language Treble
command.

## Quick start

Requires **Python 3.12+** and an internet connection. Nothing else.

```bash
cd treble_demo
./run.sh
```

On the first run, `run.sh`:

- creates a local `.venv` with Python 3.12+,
- installs Treble, `von-sdk`, and `huggingface_hub`,
- downloads the `treble-400m` checkpoint (~3 GB) from Hugging Face,
- starts the local Von server on `127.0.0.1:8765`,
- runs the Old Way, then the Treble Way.

Later runs reuse the venv, the cached model, and the server if it is still up.

## What's in here

| Path | Purpose |
| --- | --- |
| `run.sh` | One-command bootstrap + demo runner. |
| `scripts/run_vba_macro.py` | Mock Excel/VBA runner. Requires five flags and prints a weekly-report log. |
| `scripts/old_way.sh` | The literal long, manual invocation. |
| `config/weekly_report.json` | Mock workbook/report configuration. |
| `.treble/procedures/run-thursday-vba.yaml` | The Treble registry entry. |

Treble uses a directory-based YAML registry, **not** a single `registry.json`.
The equivalent registry file for this demo is
`.treble/procedures/run-thursday-vba.yaml`.

## The Old Way (type the full command)

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

Missing or mistyped flags produce standard errors, which is a good live beat:

```bash
# Mistype --target-date as --target_date (underscore):
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
3. Switch to the Treble Way below: `.venv/bin/treble "run thursday vba"`.

## The Treble Way

After `./run.sh` has installed everything, make sure Von is running (use
`KEEP_VON=1 ./run.sh`, or start it manually below), then:

```bash
cd treble_demo

export TREBLE_DECISION_URL="http://127.0.0.1:8765/v1/systemone"
.venv/bin/treble "run thursday vba"
```

The same procedure, with every path, flag, date, and macro name already in the
registry. All of these route to it too:

```bash
.venv/bin/treble "execute weekly report macro"
.venv/bin/treble "run thursda vba macro"     # misspelled on purpose
.venv/bin/treble run thursday vba            # unquoted form
```

`run.sh` stops Von when it exits unless you set `KEEP_VON=1`. To leave the
server running for a recording:

```bash
KEEP_VON=1 ./run.sh
```

Or start Von manually in its own terminal after the first run:

```bash
VON_CHECKPOINT_DIR="$HOME/.treble/models/treble-400m" \
  VON_CHAINS_DIR=off .venv/bin/von serve --host 127.0.0.1 --port 8765
```

Then point Treble at it:

```bash
export TREBLE_DECISION_URL="http://127.0.0.1:8765/v1/systemone"
```

### Deterministic (no model server required)

```bash
.venv/bin/treble list                        # show the registered procedure
.venv/bin/treble explain run-thursday-vba    # exact argv + working directory
.venv/bin/treble test run-thursday-vba       # run by name, bypassing the model
```

### Expected ending

Both sides finish with the same success line:

```text
[SUCCESS] Macro 'ThursdayWeeklyReport' executed in 1.4s
```

## Notes

- The runner is **read-only**: it prints a log and does not write report files.
  That is why the registry entry is marked `risk: read-only`.
- The model cache is `~/.treble/models/treble-400m`. Override it with
  `TREBLE_MODEL_DIR=/path/to/checkpoint`.
- If Python 3.12+ is not on your `PATH`, set `TREBLE_PYTHON` to a compatible
  interpreter.
- Treble writes routing state (`.treble/events.jsonl`, `.treble/audit.jsonl`)
  after a run. Those files are gitignored.
- Run everything from `treble_demo/`; the registry entry uses `working_dir: .`
  and paths relative to that directory.
