from __future__ import annotations

import pytest

from backend.app.config import Settings


def test_production_requires_technical_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("TECHNICAL_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="TECHNICAL_API_KEY"):
        Settings.from_environment()


def test_production_accepts_technical_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("TECHNICAL_API_KEY", "a-long-server-side-secret")

    settings = Settings.from_environment()

    assert settings.environment == "production"
    assert settings.technical_api_key == "a-long-server-side-secret"
