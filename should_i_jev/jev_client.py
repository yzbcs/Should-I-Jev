"""Optional Jev API client for the self-check: "use Jev to find where Jev belongs".

Two transports:

* **real** — POSTs a typed Choice question to ``$JEV_BASE_URL/decisions`` with
  ``Authorization: Bearer $JEV_API_KEY`` (schema is illustrative; adapt to the
  Jev API you run against). No key or URL configured → never touches the network.
* **mock** (default) — an offline stand-in whose answers mirror the heuristic
  score, so the plumbing and report can be demoed without any endpoint.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Sequence


class JevError(RuntimeError):
    pass


def ask_choice(
    question: str,
    options: Sequence[str],
    state: Optional[Dict] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout: float = 10.0,
) -> Dict:
    """Ask a Choice question. Returns {"choice": str, "p": float, "mock": bool}."""
    base_url = (base_url or os.environ.get("JEV_BASE_URL") or "").strip()
    api_key = (api_key or os.environ.get("JEV_API_KEY") or "").strip()
    if not base_url or base_url.startswith("mock"):
        return _mock_choice(question, options, state)

    payload = {
        "model": "jev-latest",
        "type": "choice",
        "question": question,
        "options": list(options),
    }
    if state is not None:
        payload["state"] = state
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        base_url.rstrip("/") + "/decisions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise JevError(f"Jev API call failed: {exc}") from exc
    choice = data.get("choice") if isinstance(data, dict) else None
    p = data.get("p") if isinstance(data, dict) else None
    if not isinstance(choice, str) or choice not in options:
        raise JevError(f"unexpected Jev API response: {data!r}")
    return {"choice": choice, "p": p if isinstance(p, (int, float)) else None, "mock": False}


def _mock_choice(question: str, options: Sequence[str], state: Optional[Dict]) -> Dict:
    # offline stand-in: mirrors the heuristic score carried in `state`
    score = 0.0
    if isinstance(state, dict):
        try:
            score = float(state.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
    p_yes = min(0.99, max(0.02, score))
    say_yes = p_yes >= 0.5
    choice = ("yes" if say_yes else "no")
    if choice not in options:
        choice = sorted(options)[0]
    return {
        "choice": choice,
        "p": round(p_yes if say_yes else 1.0 - p_yes, 4),
        "mock": True,
    }
