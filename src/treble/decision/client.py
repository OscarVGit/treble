"""Client abstraction for the System One decision API.

``HttpSystemOneClient`` speaks to Von (or TypeSafe Jev) over the
``/v1/systemone`` HTTP endpoint. Tests substitute a ``FakeSystemOneClient``
or monkeypatch :func:`default_client`. Connection and HTTP errors are
allowed to propagate so the caller can fail closed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Self, runtime_checkable

import httpx

from treble.decision.protocol import (
    ROUTE_QUESTION_ID,
    ChoiceAnswer,
    ChoiceQuestion,
    NoulAnswer,
    NoulQuestion,
    parse_choice_answer,
    parse_noul_answer,
)

if TYPE_CHECKING:
    from treble.config import TrebleConfig


@runtime_checkable
class SystemOneClient(Protocol):
    """Interface every decision-model client must satisfy."""

    def choose(self, state: str, question: ChoiceQuestion) -> ChoiceAnswer: ...
    def judge(self, state: str, question: NoulQuestion) -> NoulAnswer: ...


class HttpSystemOneClient:
    """HTTP client for ``/v1/systemone`` (Von ``von serve`` or TypeSafe Jev).

    ``base_url`` may be given with or without the ``/v1/systemone`` suffix;
    it is normalised to the endpoint root.
    """

    def __init__(
        self,
        base_url: str,
        timeout_s: float = 5.0,
        model: str = "von-latest",
        api_key: str | None = None,
    ) -> None:
        self._endpoint = self._normalise(base_url)
        self._model = model
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.Client(timeout=timeout_s, headers=headers)

    @staticmethod
    def _normalise(base_url: str) -> str:
        url = base_url.rstrip("/")
        if url.endswith("/v1/systemone"):
            return url
        return f"{url}/v1/systemone"

    # -- primitives --------------------------------------------------------

    def choose(self, state: str, question: ChoiceQuestion) -> ChoiceAnswer:
        data = self._post(state, question.to_wire())
        return parse_choice_answer(data, ROUTE_QUESTION_ID)

    def judge(self, state: str, question: NoulQuestion) -> NoulAnswer:
        data = self._post(state, question.to_wire())
        return parse_noul_answer(data, ROUTE_QUESTION_ID)

    # -- lifecycle ----------------------------------------------------------

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- internals -----------------------------------------------------------

    def _post(self, state: str, question_wire: dict[str, object]) -> dict[str, object]:
        body = {
            "model": self._model,
            "state": state,
            "questions": {ROUTE_QUESTION_ID: question_wire},
        }
        response = self._client.post(self._endpoint, json=body)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            msg = f"unexpected systemone response type: {type(data).__name__}"
            raise TypeError(msg)
        return data


def default_client(config: TrebleConfig) -> SystemOneClient:
    """Build the default HTTP client from resolved configuration.

    Centralised so tests can monkeypatch a single factory.
    """
    return HttpSystemOneClient(config.von_base_url, timeout_s=config.von_timeout_s)
