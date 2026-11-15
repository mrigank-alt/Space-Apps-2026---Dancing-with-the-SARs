"""Store and retrieve an Earthdata user token through the OS credential vault."""

from __future__ import annotations

import getpass

SERVICE_NAME = "groundsignal-nisar"
TOKEN_KEY = "earthdata-user-token"


def _keyring():
    try:
        import keyring
    except ImportError as exc:
        raise RuntimeError("Install dependencies with `backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt` first.") from exc
    return keyring


def store_token() -> None:
    token = getpass.getpass("Paste Earthdata user token (input hidden): ").strip()
    if not token:
        raise RuntimeError("No token entered; nothing was stored.")
    _keyring().set_password(SERVICE_NAME, TOKEN_KEY, token)
    print("Earthdata token saved in the Windows credential vault.")


def clear_token() -> None:
    vault = _keyring()
    try:
        vault.delete_password(SERVICE_NAME, TOKEN_KEY)
    except Exception:
        pass
    print("Stored Earthdata token removed, if one was present.")


def get_token() -> str | None:
    import os

    token = os.environ.get("EARTHDATA_TOKEN")
    if token:
        return token
    return _keyring().get_password(SERVICE_NAME, TOKEN_KEY)
