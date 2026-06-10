"""Event identity: referee-side resolution of pending player events.

Identity is ground truth from a checkpoint save (which event is in front)
plus the game's own event scripts (what its options are). The referee
publishes the FULL option set with stability-derived safe flags; the
choice belongs to the agent. An option is safe to arm by display index
only when no trigger-gated option above it can shift the mapping; unsafe
options are still advertised, as blocked affordances, so the agent sees
the genuine menu. When every option is gated, display slot 1 may be armed
sight-unseen — explicitly labelled a gamble, never silently.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .checkpoint import event_options_from_game, pending_player_events

GAMBLE_LABEL = "arm display slot 1 sight-unseen; every option is trigger-gated"


def identify_front_event(
    checkpoint_save: Path, game_dir: Path
) -> dict[str, Any] | None:
    """Identity document for the front-of-queue player event in a fresh
    checkpoint save, or None when the save shows no player event."""
    events = pending_player_events(checkpoint_save)
    if not events:
        return None
    front = events[0]
    options = [
        {
            "index": int(option["index"]),
            "label": option["label"],
            "safe": bool(option.get("stable")),
        }
        for option in event_options_from_game(front["event_key"], game_dir)
    ]
    identity: dict[str, Any] = {
        "event_id": front["save_event_id"] or 1,
        "event_key": front["event_key"],
        "options": options,
        "all_gated": False,
    }
    if not any(option["safe"] for option in options):
        # Dynamic mapping (or unparsed options): the only honest move left
        # is the recorded slot-1 gamble.
        identity["all_gated"] = True
        slot_one = next((o for o in options if o["index"] == 1), None)
        if slot_one is None:
            slot_one = {"index": 1, "label": "unknown option"}
            options.insert(0, slot_one)
        slot_one["safe"] = True
        slot_one["gamble"] = True
    return identity


def resolve_pending_event(
    env: Any,
    game_dir: Path,
    checkpoint_save: Path,
    settle_seconds: float = 4.0,
) -> dict[str, Any]:
    """Referee duty for live runs: checkpoint the game, identify the
    pending event, and publish event_identity.json so the next observation
    advertises the genuine option set. Saves the game — slow and
    state-changing, so callers invoke it explicitly, never per-observe.

    The presence flag is edge-triggered GUI telemetry; checkpoint saves are
    the truth path. When two fresh saves in a row show no queued player
    event while telemetry still claims a window, the flag is stale (missed
    close marker) and the referee clears it rather than deadlocking."""

    def _checkpoint() -> None:
        observation = env.observe()
        affordance = next(
            (a for a in observation["affordances"]
             if a["id"] == "checkpoint.save" and a["status"] != "blocked"),
            None,
        )
        if affordance is not None:
            env.step(
                "checkpoint.save",
                observation["observation_id"],
                rationale="Referee: fresh specimen to identify the interrupting event.",
            )

    if not env.observe()["world"]["pending_event"]:
        return {"status": "no_pending_event"}
    identity = None
    for attempt in range(2):
        _checkpoint()
        identity = identify_front_event(checkpoint_save, game_dir)
        if identity is not None:
            break
        # Window-close markers can race the save; give the bus a beat.
        time.sleep(settle_seconds)
        if env.observe()["world"]["pending_event"] is None:
            return {"status": "window_closed"}
    if identity is None:
        env.clear_stale_event_presence()
        return {"status": "presence_cleared_by_save"}
    (env.run_dir / "event_identity.json").write_text(
        json.dumps(identity, indent=2, sort_keys=True) + "\n"
    )
    return {"status": "identified", **identity}
