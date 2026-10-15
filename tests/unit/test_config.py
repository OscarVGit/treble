"""Tests for configuration resolution, including the Jev/TypeSafe backend."""

from __future__ import annotations

from pathlib import Path

import pytest

from treble.config import (
    DEFAULT_MODEL_NAME,
    DEFAULT_VON_BASE_URL,
    TrebleConfig,
)


def _clear(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "TREBLE_DECISION_URL",
        "TREBLE_VON_URL",
        "TYPESAFE_API_KEY",
        "TYPESAFE_API",
        "TREBLE_API_KEY",
        "TREBLE_MODEL",
        "TREBLE_TIMEOUT_S",
        "TREBLE_VARIANT",
    ):
        monkeypatch.delenv(var, raising=False)


def test_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear(monkeypatch)
    cfg = TrebleConfig.load(tmp_path)
    assert cfg.von_base_url == DEFAULT_VON_BASE_URL
    assert cfg.model == DEFAULT_MODEL_NAME
    assert cfg.api_key is None


def test_typesafe_api_key_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("TYPESAFE_API_KEY", "jev-secret")
    assert TrebleConfig.load(tmp_path).api_key == "jev-secret"


def test_typesafe_api_legacy_alias(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("TYPESAFE_API", "legacy-key")
    assert TrebleConfig.load(tmp_path).api_key == "legacy-key"


def test_decision_url_env_takes_precedence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("TREBLE_VON_URL", "http://von/v1/systemone")
    monkeypatch.setenv("TREBLE_DECISION_URL", "https://jev.example/v1/systemone")
    assert TrebleConfig.load(tmp_path).von_base_url == "https://jev.example/v1/systemone"


def test_model_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("TREBLE_MODEL", "jev-1")
    assert TrebleConfig.load(tmp_path).model == "jev-1"


def test_timeout_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear(monkeypatch)
    assert TrebleConfig.load(tmp_path).von_timeout_s == 5.0
    monkeypatch.setenv("TREBLE_TIMEOUT_S", "20")
    assert TrebleConfig.load(tmp_path).von_timeout_s == 20.0


def test_default_client_forwards_key_and_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from treble.decision.client import HttpSystemOneClient, default_client

    cfg = TrebleConfig(
        von_base_url="https://jev.example/v1/systemone",
        model="jev-1",
        api_key="jev-secret",
    )
    client = default_client(cfg)
    assert isinstance(client, HttpSystemOneClient)
    # Bearer key reaches the underlying HTTP client.
    assert client._client.headers.get("authorization") == "Bearer jev-secret"
