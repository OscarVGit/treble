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
treble test check-no-verify --dry-run
```
