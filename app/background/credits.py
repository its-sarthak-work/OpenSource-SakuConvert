from __future__ import annotations

import json
from datetime import date
from pathlib import Path

DAILY_LIMIT = 10


def _state_path() -> Path:
    # Keep the small local counter in the user's application-data directory.
    # It is only a UI convenience; the provider's server-side IP limit is
    # authoritative.
    base = Path.home() / "AppData" / "Local" / "SakuConvert"
    base.mkdir(parents=True, exist_ok=True)
    return base / "background_usage.json"


def _load() -> dict:
    path = _state_path()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"date": date.today().isoformat(), "used": 0}


def _normalized_state() -> dict:
    state = _load()
    today = date.today().isoformat()
    if state.get("date") != today:
        state = {"date": today, "used": 0}
        _save(state)
    return state


def _save(state: dict) -> None:
    path = _state_path()
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def used_today() -> int:
    return min(max(int(_normalized_state().get("used", 0)), 0), DAILY_LIMIT)


def remaining_today() -> int:
    return max(DAILY_LIMIT - used_today(), 0)


def record_success() -> int:
    state = _normalized_state()
    state["used"] = min(int(state.get("used", 0)) + 1, DAILY_LIMIT)
    _save(state)
    return max(DAILY_LIMIT - state["used"], 0)


def mark_exhausted() -> None:
    state = _normalized_state()
    state["used"] = DAILY_LIMIT
    _save(state)
