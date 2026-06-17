"""REST routes for the interactive replay track, mounted under ``/interactive``.

This is the only seam between backend (Claude) and frontend (Codex). The handler
object passed in is the server's ``BaseHTTPRequestHandler`` subclass; we reuse
its ``_json`` helper and raw ``rfile``/``headers`` for the body. No classic route
is touched — server.py only forwards ``/interactive/*`` here.
"""

from __future__ import annotations

import json
import threading
import traceback
from typing import Any

from .session import InteractiveSession, list_interactive_datasets


_STATE: dict[str, Any] = {"session": None, "lock": threading.Lock()}


def _read_json(handler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0") or 0)
    if not length:
        return {}
    body = handler.rfile.read(length).decode("utf-8")
    return json.loads(body) if body.strip() else {}


def _require_session() -> InteractiveSession:
    session = _STATE["session"]
    if session is None:
        raise LookupError("no interactive session — call /interactive/session/new first")
    return session


def handle(handler, method: str, path: str) -> bool:
    """Dispatch an /interactive/* request. Returns True if handled."""
    try:
        return _dispatch(handler, method, path)
    except LookupError as exc:
        handler._json({"ok": False, "error": str(exc)}, status=409)
        return True
    except (KeyError, ValueError, FileNotFoundError) as exc:
        handler._json({"ok": False, "error": str(exc)}, status=400)
        return True
    except Exception as exc:  # noqa: BLE001 — surface as 500 JSON, keep server alive
        traceback.print_exc()
        handler._json({"ok": False, "error": str(exc)}, status=500)
        return True


def _dispatch(handler, method: str, path: str) -> bool:
    if method == "GET" and path == "/interactive/catalog":
        handler._json(
            {
                "datasets": list_interactive_datasets(),
                "strategies": ["sr_quant", "fvg", "stub"],
                "modes": ["SEM", "COM", "AMBOS"],
            }
        )
        return True

    if method == "POST" and path == "/interactive/session/new":
        payload = _read_json(handler)
        with _STATE["lock"]:
            session = InteractiveSession.from_config(
                payload.get("config"),
                strategy=payload.get("strategy", "sr_quant"),
                mode=payload.get("mode", "SEM"),
                symbol=payload.get("symbol"),
                timeframe=payload.get("timeframe"),
                engine=payload.get("engine"),
            )
            _STATE["session"] = session
            info = session.session_info()
        handler._json(info)
        return True

    if method == "POST" and path == "/interactive/step":
        payload = _read_json(handler)
        with _STATE["lock"]:
            handler._json(_require_session().step(int(payload.get("n", 1))))
        return True

    if method == "POST" and path == "/interactive/reset":
        with _STATE["lock"]:
            handler._json(_require_session().reset())
        return True

    if method == "POST" and path == "/interactive/seek":
        payload = _read_json(handler)
        with _STATE["lock"]:
            handler._json(_require_session().seek(int(payload.get("bar", 0))))
        return True

    if method == "POST" and path == "/interactive/series":
        payload = _read_json(handler)
        with _STATE["lock"]:
            handler._json(_require_session().series(payload.get("tf")))
        return True

    if method == "GET" and path == "/interactive/state":
        with _STATE["lock"]:
            handler._json(_require_session().snapshot())
        return True

    if method == "GET" and path == "/interactive/zones":
        with _STATE["lock"]:
            handler._json({"zones": _require_session().active_zones()})
        return True

    if method == "POST" and path == "/interactive/zone":
        payload = _read_json(handler)
        with _STATE["lock"]:
            zone = _require_session().add_zone(
                price_low=payload["price_low"],
                price_high=payload["price_high"],
                side=payload.get("side", "support"),
                timeframe=payload.get("timeframe", ""),
            )
        handler._json(zone)
        return True

    if method == "PUT" and path.startswith("/interactive/zone/"):
        zid = path.rsplit("/", 1)[-1]
        payload = _read_json(handler)
        with _STATE["lock"]:
            handler._json(_require_session().update_zone(zid, payload))
        return True

    if method == "DELETE" and path.startswith("/interactive/zone/"):
        zid = path.rsplit("/", 1)[-1]
        with _STATE["lock"]:
            handler._json(_require_session().delete_zone(zid))
        return True

    if method == "POST" and path == "/interactive/finish":
        with _STATE["lock"]:
            handler._json(_require_session().finish())
        return True

    return False
