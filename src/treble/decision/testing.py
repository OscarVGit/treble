"""Test/utility doubles for the Von decision client.

Kept in the package (not under ``tests/``) so the offline eval harness and
external tooling can script a client without a live Von server.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from treble.decision.protocol import (
    ChoiceAnswer,
    ChoiceQuestion,
    NoulAnswer,
    NoulQuestion,
)


@dataclass
class FakeSystemOneClient:
    """Scripted SystemOneClient.

    Script the primitives independently:
    - ``noul_probability``: value returned by every ``judge`` call (the run
      gate). ``>= 0.5`` routes to the run path, ``< 0.5`` to control.
    - ``answer``: the ChoiceAnswer returned by ``choose`` (run-target or
      control-verb). For targeted control verbs, the *same* client must answer
      two Choice calls (verb then target); use ``answers`` to script both.
    - ``answers``: an ordered list of ChoiceAnswers consumed one per ``choose``.
    - ``error``: raised by every call to simulate Von being unreachable.

    Records every call in ``calls`` as ``("judge"|"choose", state, question)``.
    """

    noul_probability: float = 1.0
    answer: ChoiceAnswer | None = None
    answers: list[ChoiceAnswer] | None = None
    noul_series: list[float] | None = None  # consumed one per judge call
    error: Exception | None = None
    calls: list[tuple[str, str, object]] = field(default_factory=list)

    def judge(self, state: str, question: NoulQuestion) -> NoulAnswer:
        self.calls.append(("judge", state, question))
        if self.error is not None:
            raise self.error
        if self.noul_series:
            prob = self.noul_series.pop(0)
            return NoulAnswer(noul=prob, noul_raw=prob)
        return NoulAnswer(noul=self.noul_probability, noul_raw=self.noul_probability)

    def choose(self, state: str, question: ChoiceQuestion) -> ChoiceAnswer:
        self.calls.append(("choose", state, question))
        if self.error is not None:
            raise self.error
        if self.answers:
            return self.answers.pop(0)
        assert self.answer is not None, "FakeSystemOneClient needs an answer"
        return self.answer


def make_answer(choice: str, probabilities: dict[str, float]) -> ChoiceAnswer:
    """Build a ChoiceAnswer with confidence = the winning key's probability."""
    return ChoiceAnswer(
        choice=choice,
        probabilities=probabilities,
        confidence=probabilities.get(choice, 0.0),
    )
