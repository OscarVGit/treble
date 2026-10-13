# Example procedures

These YAML files are **examples**, not auto-loaded. Copy any of them into
a scope directory to make them active:

- Project scope:  `./.treble/procedures/`
- Personal scope: `~/.treble/procedures/`

```bash
mkdir -p .treble/procedures
cp procedures/examples/check-no-verify.yaml .treble/procedures/
treble list
treble explain check-no-verify
treble test check-no-verify          # deterministic by-name run
treble check-no-verify --watch       # argument forwarding: stored argv + --watch
```

Register real procedures with the CLI instead of hand-writing YAML:

```bash
treble-add "pnpm run check --no-verify" --name check-no-verify \
  --description "Run checks without verification" --alias cnv
```

Note the flag-ownership rule when experimenting: `--dry-run`/`--yes`
*before* the identifier are Treble's; after the identifier they are
forwarded to the command.
