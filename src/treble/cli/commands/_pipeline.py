"""Shared execution pipeline for ``treble run``.

Every free-form request is routed through Von — there is no deterministic
regex/exact-match short-circuit. The pipeline:

1. loads the enabled procedures (neutral registry order),
2. asks Von to choose a single finite action,
3. dispatches to the corresponding deterministic handler,
4. enforces the safety policy (confirmations, dry-run, risk gates),
5. executes and records an audit/outcome trail for runs.

If Von is unreachable the pipeline fails closed: it returns
``EXIT_VON_UNAVAILABLE`` and never falls back to string matching.

Safety boundary: Von *selects*; the runtime *enforces*. Mutating actions
honour ``--dry-run`` and the confirmation/policy gates regardless of how
confident the model was.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import typer

from treble.config import TrebleConfig
from treble.decision import Action, SystemOneClient, decide, default_client
from treble.registry import Procedure, ProcedureNotFound, ProcedureStore
from treble.runtime import (
    AuditRecord,
    PolicyDecision,
    SafetyPolicy,
    append_audit,
    execute,
    verify,
)
from treble.verification import LearningStore

EXIT_OK = 0
EXIT_NO_MATCH = 2
EXIT_NEEDS_DECISION = 3
EXIT_DENIED = 4
EXIT_FAILED = 5
EXIT_VON_UNAVAILABLE = 6
EXIT_CLARIFY = 7


def run_pipeline(
    tokens: list[str],
    *,
    cwd: Path | None = None,
    dry_run: bool = False,
    assume_yes: bool = False,
    policy: SafetyPolicy | None = None,
    client: SystemOneClient | None = None,
) -> int:
    """Route ``tokens`` through Von and dispatch the chosen action."""
    cfg = TrebleConfig.load(cwd)
    policy = policy or SafetyPolicy()
    store = ProcedureStore(cwd)
    procedures = [p for p in store.list_all() if p.enabled]
    client = client or default_client(cfg)

    try:
        outcome = decide(tokens, procedures, client, cwd=cwd)
    except (httpx.HTTPError, httpx.RequestError, OSError) as exc:
        typer.secho(
            "Von decision model is unreachable "
            f"({exc.__class__.__name__}). Treble requires Von to route "
            "requests and will not fall back to string matching.",
            fg="red",
            err=True,
        )
        return EXIT_VON_UNAVAILABLE

    return _dispatch(
        outcome_action=outcome.action,
        target_name=outcome.target_name,
        store=store,
        cwd=cwd,
        dry_run=dry_run,
        assume_yes=assume_yes,
        policy=policy,
        outcome=outcome,
    )


def run_procedure_by_name(
    name: str,
    *,
    cwd: Path | None = None,
    dry_run: bool = False,
    assume_yes: bool = False,
    policy: SafetyPolicy | None = None,
) -> int:
    """Execute a named procedure directly, bypassing Von.

    Used by the literal ``treble test <name>`` subcommand. This is the CLI's
    own deterministic control surface, not a fallback for a Von-routed
    request.
    """
    store = ProcedureStore(cwd)
    procedure = _resolve(store, name)
    if procedure is None:
        return EXIT_NO_MATCH
    return _run_procedure(
        procedure,
        cwd=cwd,
        dry_run=dry_run,
        assume_yes=assume_yes,
        policy=policy or SafetyPolicy(),
    )


def _dispatch(
    *,
    outcome_action: Action,
    target_name: str | None,
    store: ProcedureStore,
    cwd: Path | None,
    dry_run: bool,
    assume_yes: bool,
    policy: SafetyPolicy,
    outcome,  # DecisionOutcome; only needed for CLARIFY formatting
) -> int:
    """Execute the handler for the chosen action."""
    if outcome_action is Action.SELECT_PROCEDURE or outcome_action is Action.TEST:
        procedure = _resolve(store, target_name)
        if procedure is None:
            return EXIT_NO_MATCH
        return _run_procedure(
            procedure, cwd=cwd, dry_run=dry_run, assume_yes=assume_yes, policy=policy
        )

    if outcome_action is Action.REMOVE_PROCEDURE:
        return _remove(store, target_name, dry_run=dry_run, assume_yes=assume_yes)

    if outcome_action is Action.SHOW:
        procedure = _resolve(store, target_name)
        if procedure is None:
            return EXIT_NO_MATCH
        _show(procedure)
        return EXIT_OK

    if outcome_action is Action.EXPLAIN:
        procedure = _resolve(store, target_name)
        if procedure is None:
            return EXIT_NO_MATCH
        _explain(procedure, cwd)
        return EXIT_OK

    if outcome_action is Action.LIST:
        _list(store)
        return EXIT_OK

    if outcome_action is Action.ADD_PROCEDURE:
        typer.echo(
            "To add a procedure, register it explicitly (reviewed before use):\n"
            "  treble-add --name <name> --command '<exact command>' "
            "--description '<what it does>'"
        )
        return EXIT_NEEDS_DECISION

    if outcome_action is Action.CLARIFY:
        _print_clarification(outcome)
        return EXIT_CLARIFY

    if outcome_action is Action.REJECT:
        typer.secho("request rejected by policy", fg="red", err=True)
        return EXIT_DENIED

    # Action.ESCALATE and anything unrecognised.
    typer.secho(
        "no suitable action: Von could not match the request to a registered "
        "procedure or command.",
        fg="yellow",
    )
    return EXIT_NEEDS_DECISION


# -- handlers ---------------------------------------------------------------


def _resolve(store: ProcedureStore, name: str | None) -> Procedure | None:
    if not name:
        typer.secho("Von chose an action without a target procedure", fg="red", err=True)
        return None
    try:
        return store.get(name)
    except ProcedureNotFound:
        typer.secho(f"no procedure named {name!r}", fg="red", err=True)
        return None


def _run_procedure(
    procedure: Procedure,
    *,
    cwd: Path | None,
    dry_run: bool,
    assume_yes: bool,
    policy: SafetyPolicy,
) -> int:
    decision = policy.decide(procedure)
    if decision is PolicyDecision.DENY:
        typer.secho(f"policy denies execution of {procedure.name!r}", fg="red", err=True)
        return EXIT_DENIED
    if decision is PolicyDecision.CONFIRM and not (assume_yes or dry_run):
        confirmed = typer.confirm(
            f"Run {procedure.name!r} ({procedure.risk})? argv={procedure.invocation()}"
        )
        if not confirmed:
            return EXIT_DENIED

    if dry_run:
        typer.echo(f"[dry-run] would execute: {' '.join(procedure.invocation())}")
        typer.echo(f"[dry-run] cwd: {procedure.working_dir or (cwd or Path.cwd())}")
        return EXIT_OK

    result = execute(procedure, cwd=cwd)
    outcome = verify(procedure.verify, result, cwd=cwd)
    append_audit(AuditRecord.from_execution(result, verified=outcome.passed), cwd=cwd)
    LearningStore(cwd).record_outcome(
        procedure.name,
        procedure.fingerprint(),
        succeeded=result.succeeded,
        verified=outcome.passed,
    )

    if result.stdout:
        typer.echo(result.stdout, nl=False)
    if result.stderr:
        typer.echo(result.stderr, err=True, nl=False)

    if not outcome.passed:
        for failure in outcome.failures:
            typer.secho(f"verification: {failure}", fg="red", err=True)
        return EXIT_FAILED
    return EXIT_OK if result.succeeded else EXIT_FAILED


def _remove(
    store: ProcedureStore, name: str | None, *, dry_run: bool, assume_yes: bool
) -> int:
    procedure = _resolve(store, name)
    if procedure is None:
        return EXIT_NO_MATCH
    if dry_run:
        typer.echo(f"[dry-run] would remove {procedure.name!r}")
        return EXIT_OK
    if not assume_yes and not typer.confirm(f"Remove {procedure.name!r}?"):
        return EXIT_DENIED
    path = store.remove(procedure.name)
    typer.echo(f"removed {procedure.name!r} ({path})")
    return EXIT_OK


def _show(procedure: Procedure) -> None:
    import yaml

    from treble.registry.models import procedure_to_yaml_dict

    typer.echo(yaml.safe_dump(procedure_to_yaml_dict(procedure), sort_keys=False))


def _explain(procedure: Procedure, cwd: Path | None) -> None:
    typer.echo(f"procedure: {procedure.name}")
    typer.echo(f"argv:      {' '.join(procedure.invocation())}")
    typer.echo(f"risk:      {procedure.risk}")
    typer.echo(f"cwd:       {procedure.working_dir or (cwd or Path.cwd())}")
    if procedure.verify.expected_exit_code != 0:
        typer.echo(f"verify:    exit code must be {procedure.verify.expected_exit_code}")


def _list(store: ProcedureStore) -> None:
    procedures = store.list_all()
    if not procedures:
        typer.echo("no procedures registered")
        return
    for proc in procedures:
        typer.echo(f"{proc.name:24s} [{proc.scope:8s}] [{proc.risk:11s}] {proc.description}")


def _print_clarification(outcome) -> None:
    """Show the top options Von considered so the user can disambiguate."""
    typer.secho("ambiguous request — Von's top candidates:", fg="yellow")
    ranked = sorted(outcome.probabilities.items(), key=lambda kv: kv[1], reverse=True)
    for key, prob in ranked[:4]:
        description = outcome.options.get(key, "")
        typer.echo(f"  {prob:0.2f}  {key:32s} {description}")
