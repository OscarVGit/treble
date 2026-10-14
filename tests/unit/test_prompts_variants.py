"""Unit tests for prompt variants (A/B measurement registry)."""

from __future__ import annotations

import pytest

from treble.decision.prompts import (
    DEFAULT_VARIANT,
    RUN_GATE_CONDITION,
    VARIANTS,
    Variant,
    build_routing_state,
    get_variant,
)


def test_default_variant_registered_and_identity() -> None:
    assert get_variant("default") is DEFAULT_VARIANT
    assert DEFAULT_VARIANT.run_gate_condition == RUN_GATE_CONDITION
    assert DEFAULT_VARIANT.run_gate_state_extra == ""


def test_compact_gate_variant_present() -> None:
    variant = get_variant("compact-gate")
    assert variant.name == "compact-gate"
    # Hypothesis: a short classifier instruction replaces the verbose one.
    assert variant.run_gate_condition == "Is this a request to run a registered procedure?"
    # And the domain rule moved into the state as a framing line.
    assert "name a procedure" in variant.run_gate_state_extra


def test_compact_gate_differs_from_default() -> None:
    default = get_variant("default")
    compact = get_variant("compact-gate")
    assert default.run_gate_condition != compact.run_gate_condition
    assert default.run_gate_state_extra != compact.run_gate_state_extra
    # Target instructions stay aligned across variants for now.
    assert default.run_target_instructions == compact.run_target_instructions


def test_unknown_variant_raises_with_available_names() -> None:
    with pytest.raises(ValueError, match="unknown prompt variant"):
        get_variant("nope")


def test_variants_dict_keys() -> None:
    assert set(VARIANTS) == {"default", "compact-gate", "folded", "verb-first-gate"}


def test_verb_first_gate_variant_prefers_inspection_verbs() -> None:
    variant = get_variant("verb-first-gate")
    assert variant.run_gate_condition != RUN_GATE_CONDITION
    assert "inspection request" in variant.run_gate_condition
    assert variant.folded is False


def test_folded_variant_flag_and_action_options() -> None:
    folded = get_variant("folded")
    assert folded.folded is True
    assert get_variant("default").folded is False
    from treble.decision.prompts import RUN_ACTION, build_action_options

    options = build_action_options()
    assert RUN_ACTION in options
    for verb in ("list", "show", "explain", "test", "remove", "add"):
        assert verb in options


def test_build_routing_state_includes_extra_framing_line() -> None:
    state = build_routing_state(["hello"], [], extra="Bare names count as run.")
    assert "Bare names count as run." in state


def test_build_routing_state_no_extra_by_default() -> None:
    state = build_routing_state(["hello"], [])
    assert "Short requests" not in state
    assert state.count("\n\n") >= 1


def test_variant_dataclass_defaults() -> None:
    v = Variant(name="x")
    assert v.run_gate_state_extra == ""
    assert v.run_gate_condition == RUN_GATE_CONDITION
