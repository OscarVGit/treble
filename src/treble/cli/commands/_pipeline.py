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

import time
from pathlib import Path

import httpx
import typer

from treble.config import TrebleConfig
from treble.decision import Action, SystemOneClient, decide, default_client
from treble.registry import Procedure, ProcedureNotFound, ProcedureStore
from treble.runtime import (
    AuditRecord,
    EventRecord,
    PolicyDecision,
    SafetyPolicy,
    append_audit,
    append_event,
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


def _log_event(
    cwd: Path | None,
    *,
    source: str,
    action: str,
    target: str | None,
    reason: str | None = None,
    confidence: float | None = None,
    exit_code: int = 0,
) -> None:
    """Append one routing event (best-effort; never breaks a request)."""
    try:
        append_event(
            EventRecord(
                ts=time.time(),
                source=source,
                action=action,
                target=target,
                confidence=confidence,
                reason=reason,
                exit_code=exit_code,
            ),
            cwd=cwd,
        )
    except OSError:
        pass


def run_pipeline(
    tokens: list[str],
    *,
    cwd: Path | None = None,
    dry_run: bool = False,
    assume_yes: bool = False,
    policy: SafetyPolicy | None = None,
    client: SystemOneClient | None = None,
    variant: str | None = None,
) -> int:
    """Route ``tokens`` and dispatch the chosen action.

    Argument forwarding (leading registered identifier + trailing flags) is
    resolved deterministically first; everything else is routed through Von.
    ``variant`` selects the prompt configuration (env ``TREBLE_VARIANT``).
    """
    cfg = TrebleConfig.load(cwd)
    policy = policy or SafetyPolicy()
    store = ProcedureStore(cwd)
    procedures = [p for p in store.list_all() if p.enabled]
    chosen_variant = variant or cfg.variant

    # Deterministic argument forwarding (no Von call).
    from treble.matching import match_forward

    forward = match_forward(tokens, procedures)
    if forward is not None:
        code = _run_procedure(
            forward.procedure,
            cwd=cwd,
            dry_run=dry_run,
            assume_yes=assume_yes,
            policy=policy,
            extra_args=forward.extras,
            source="forwarding",
        )
        _log_event(
            cwd,
            source="forwarding",
            action="select",
            target=forward.procedure.name,
            reason="argument forwarding",
            exit_code=code,
        )
        return code

    client = client or default_client(cfg)

    try:
        outcome = decide(tokens, procedures, client, cwd=cwd, variant=chosen_variant)
    except (httpx.HTTPError, httpx.RequestError, OSError) as exc:
        typer.secho(
            "Treble's decision service is unreachable "
            f"({exc.__class__.__name__}). Treble could not route the request; "
            "start the decision service and retry.",
            fg="red",
            err=True,
        )
        _log_event(
            cwd,
            source="routed",
            action="error",
            target=None,
            reason=exc.__class__.__name__,
            exit_code=EXIT_VON_UNAVAILABLE,
        )
        return EXIT_VON_UNAVAILABLE

    code = _dispatch(
        outcome_action=outcome.action,
        target_name=outcome.target_name,
        store=store,
        cwd=cwd,
        dry_run=dry_run,
        assume_yes=assume_yes,
        policy=policy,
        outcome=outcome,
    )
    _log_event(
        cwd,
        source="routed",
        action=outcome.action.value,
        target=outcome.target_name,
        confidence=outcome.confidence,
        reason=outcome.reason,
        exit_code=code,
    )
    return code


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
        _log_event(cwd, source="literal", action="test", target=name,
                   reason="not found", exit_code=EXIT_NO_MATCH)
        return EXIT_NO_MATCH
    code = _run_procedure(
        procedure,
        cwd=cwd,
        dry_run=dry_run,
        assume_yes=assume_yes,
        policy=policy or SafetyPolicy(),
        source="literal",
    )
    _log_event(cwd, source="literal", action="test", target=procedure.name,
               reason="literal test", exit_code=code)
    return code


def remove_procedure_by_name(
    name: str,
    *,
    cwd: Path | None = None,
    dry_run: bool = False,
    assume_yes: bool = False,
) -> int:
    """Remove a named procedure directly, bypassing Von.

    Used by the literal ``treble remove`` subcommand. Mirrors the model path's
    ``_remove`` so the deterministic control surface applies the same
    confirmation and dry-run gates rather than deleting outright.
    """
    store = ProcedureStore(cwd)
    code = _remove(store, name, dry_run=dry_run, assume_yes=assume_yes)
    _log_event(cwd, source="literal", action="remove", target=name,
               reason="literal remove", exit_code=code)
    return code


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
            procedure,
            cwd=cwd,
            dry_run=dry_run,
            assume_yes=assume_yes,
            policy=policy,
            confirm=outcome.confirm,
            confirm_reason=outcome.confirm_reason,
            showdown_runner_up=outcome.runner_up,
            source="routed",
            decision_reason=outcome.reason,
            decision_confidence=outcome.confidence,
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
        "no suitable action: Treble could not match the request to a registered "
        "procedure or command.",
        fg="yellow",
    )
    return EXIT_NEEDS_DECISION


# -- handlers ---------------------------------------------------------------


def _resolve(store: ProcedureStore, name: str | None) -> Procedure | None:
    if not name:
        typer.secho("Treble chose an action without a target procedure", fg="red", err=True)
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
    extra_args: list[str] | None = None,
    confirm: bool = False,
    confirm_reason: str = "",
    showdown_runner_up: str | None = None,
    source: str = "unknown",
    decision_reason: str | None = None,
    decision_confidence: float | None = None,
) -> int:
    full_argv = [*procedure.invocation(), *(extra_args or [])]

    # Confirmation gate. Two sources require it before execution:
    #   * a mutating/destructive selection (``confirm_reason`` set) — the
    #     safety property: never silently execute a mutating action; and
    #   * a near-tied pick whose showdown Noul was unsure (contested pick).
    # --yes and --dry-run bypass the prompt (explicit intent / no execution).
    if confirm and not (assume_yes or dry_run):
        if confirm_reason:
            prompt = f"{confirm_reason}. Run {procedure.name!r}? argv={full_argv}"
        elif showdown_runner_up and showdown_runner_up != procedure.name:
            prompt = (
                f"Treble is unsure between {procedure.name!r} and "
                f"{showdown_runner_up!r}. Run {procedure.name!r} anyway? "
                f"argv={full_argv}"
            )
        else:
            prompt = f"Treble is unsure about this pick. Run {procedure.name!r}? argv={full_argv}"
        if not typer.confirm(prompt):
            typer.secho(f"cancelled {procedure.name!r}", fg="yellow")
            return EXIT_CLARIFY

    decision = policy.decide(procedure)
    if decision is PolicyDecision.DENY:
        typer.secho(f"policy denies execution of {procedure.name!r}", fg="red", err=True)
        return EXIT_DENIED
    if decision is PolicyDecision.CONFIRM and not (assume_yes or dry_run):
        confirmed = typer.confirm(
            f"Run {procedure.name!r} ({procedure.risk})? argv={full_argv}"
        )
        if not confirmed:
            return EXIT_DENIED

    if dry_run:
        typer.echo(f"[dry-run] would execute: {' '.join(full_argv)}")
        typer.echo(f"[dry-run] cwd: {procedure.working_dir or (cwd or Path.cwd())}")
        return EXIT_OK

    result = execute(procedure, cwd=cwd, extra_args=extra_args)
    outcome = verify(procedure.verify, result, cwd=cwd)
    append_audit(
        AuditRecord.from_execution(
            result,
            verified=outcome.passed,
            source=source,
            decision_reason=decision_reason,
            decision_confidence=decision_confidence,
        ),
        cwd=cwd,
    )
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
        _report_failure(procedure, result, outcome)
        return EXIT_FAILED
    return EXIT_OK if result.succeeded else EXIT_FAILED


def _report_failure(procedure: Procedure, result, outcome) -> None:
    """Print an actionable message for common execution failures.

    127 (command not found) and ENOENT-style failures from missing tooling
    are the most common; explain them instead of a bare exit-code mismatch.
    """
    executable = result.argv[0] if result.argv else procedure.executable or "?"
    for failure in outcome.failures:
        typer.secho(f"verification: {failure}", fg="red", err=True)

    if result.exit_code in (127,) or (result.error and "No such file" in result.error):
        typer.secho(
            f"command {executable!r} was not found on PATH (exit 127). "
            "Install it, put it on PATH, or register a procedure that uses an "
            "available executable.",
            fg="yellow",
            err=True,
        )
    elif "ENOENT" in (result.stderr or ""):
        typer.secho(
            "command failed with ENOENT — did you run it in the right working "
            "directory (e.g. a project containing package.json)?",
            fg="yellow",
            err=True,
        )


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
    """Show the top options Treble considered so the user can disambiguate."""
    typer.secho("ambiguous request — Treble's top candidates:", fg="yellow")
    ranked = sorted(outcome.probabilities.items(), key=lambda kv: kv[1], reverse=True)
    for key, prob in ranked[:4]:
        description = outcome.options.get(key, "")
        typer.echo(f"  {prob:0.2f}  {key:32s} {description}")
