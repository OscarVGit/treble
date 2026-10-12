"""Typed wire protocol for the TypeSafe ``/v1/systemone`` API.

Von (and TypeSafe Jev) expose a single endpoint. A request carries a
``state`` (the user's request as text) and a ``questions`` mapping. Each
question has a ``type`` — ``choice``, ``noul`` or ``score`` — plus
``instructions`` and ``criteria``.

For a Choice question, ``criteria`` maps an *option key* to a *natural
-language description*. Von returns the winning key, the full probability
distribution over keys, and a calibrated confidence. Treble uses opaque
keys (``select:NAME``, ``list``, ``none-of-the-above``) so the model's
choice maps directly onto a finite action without any string parsing of
natural language.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# The single question id Treble uses for routing.
ROUTE_QUESTION_ID = "route"


@dataclass(frozen=True)
class ChoiceQuestion:
    """A Choice question: pick the best option key for the given state."""

    instructions: str
    criteria: dict[str, str]  # option key -> description
    type: str = "choice"

    def to_wire(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "instructions": self.instructions,
            "criteria": dict(self.criteria),
        }


@dataclass(frozen=True)
class ChoiceAnswer:
    """The parsed answer to a Choice question."""

    choice: str
    probabilities: dict[str, float] = field(default_factory=dict)
    confidence: float = 0.0

    @property
    def winning_probability(self) -> float:
        return self.probabilities.get(self.choice, self.confidence)

    def top_two(self) -> tuple[tuple[str, float], tuple[str, float]] | None:
        """The two highest-probability (key, probability) pairs, if available."""
        if len(self.probabilities) < 2:
            return None
        ordered = sorted(self.probabilities.items(), key=lambda kv: kv[1], reverse=True)
        return ordered[0], ordered[1]

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> ChoiceAnswer:
        probs = {
            str(k): float(v)
            for k, v in (payload.get("probabilities") or {}).items()
        }
        choice = str(payload.get("choice", ""))
        confidence = float(payload.get("confidence", probs.get(choice, 0.0)))
        return cls(choice=choice, probabilities=probs, confidence=confidence)


def parse_choice_answer(response_body: dict[str, Any], question_id: str = ROUTE_QUESTION_ID) -> ChoiceAnswer:
    """Extract the ChoiceAnswer for ``question_id`` from a systemone response body."""
    answer = _extract_answer(response_body, question_id)
    return ChoiceAnswer.from_json(answer)


@dataclass(frozen=True)
class NoulQuestion:
    """A Noul question: probability that a condition holds over the state."""

    instructions: str
    criteria: dict[str, str] | None = None
    type: str = "noul"

    def to_wire(self) -> dict[str, Any]:
        wire: dict[str, Any] = {"type": self.type, "instructions": self.instructions}
        if self.criteria:
            wire["criteria"] = dict(self.criteria)
        return wire


@dataclass(frozen=True)
class NoulAnswer:
    """The parsed answer to a Noul question.

    ``noul`` is the committed band decision (sits near 0.15/0.2 or 0.8/0.85
    under Von's band rule); ``noul_raw`` is the calibrated posterior before
    the band, which is the value to use for confidence gating.
    """

    noul: float
    noul_raw: float | None = None

    @property
    def probability(self) -> float:
        """The calibrated probability best suited for thresholding."""
        return self.noul_raw if self.noul_raw is not None else self.noul

    @property
    def holds(self) -> bool:
        return self.probability >= 0.5

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> NoulAnswer:
        raw = payload.get("noul_raw")
        return cls(
            noul=float(payload.get("noul", 0.0)),
            noul_raw=float(raw) if raw is not None else None,
        )


def parse_noul_answer(response_body: dict[str, Any], question_id: str = ROUTE_QUESTION_ID) -> NoulAnswer:
    """Extract the NoulAnswer for ``question_id`` from a systemone response body."""
    answer = _extract_answer(response_body, question_id)
    return NoulAnswer.from_json(answer)


def _extract_answer(response_body: dict[str, Any], question_id: str) -> dict[str, Any]:
    answers = response_body.get("answers")
    if not isinstance(answers, dict) or question_id not in answers:
        msg = f"systemone response missing answer for question {question_id!r}"
        raise ValueError(msg)
    answer = answers[question_id]
    if not isinstance(answer, dict):
        msg = f"systemone answer for {question_id!r} is not an object"
        raise TypeError(msg)
    return answer
