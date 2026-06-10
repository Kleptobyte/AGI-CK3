"""Survival episode runner: waits out a target number of game days,
resolving interrupting events through the identity pipeline.

Policy for interrupts: prefer the first display-index-stable option; when
every option is trigger-gated (dynamic mapping), arm display slot 1 with
the gamble recorded in the rationale. Window-close marker races are
tolerated; a persistently unidentified window ends the episode honestly.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .env import CK3Env
from .identity import resolve_pending_event


def _days(date: str) -> int:
    year, month, day = (int(part) for part in date.split("."))
    return year * 360 + (month - 1) * 30 + day


def choose_option(options: list[dict[str, Any]]) -> tuple[int, str]:
    """Scripted policy over an identity option set: first deliberate safe
    option, else the recorded slot-1 gamble."""
    deliberate = [
        option for option in options
        if option.get("safe") and not option.get("gamble")
    ]
    if deliberate:
        first = deliberate[0]
        return first["index"], f"stable option {first['index']} ('{first['label']}')"
    return 1, "all options trigger-gated; arming display slot 1 sight-unseen (recorded gamble)"


def run_survival_episode(
    env: CK3Env,
    target_days: int,
    game_dir: Path,
    checkpoint_save: Path,
    max_turns: int = 60,
    max_event_resolutions: int = 12,
) -> dict[str, Any]:
    episode = json.loads((env.run_dir / "episode.json").read_text())
    start = episode["start_date"]
    resolved = 0
    stop_reason = "max_turns"

    def step(affordance_id: str, rationale: str) -> dict[str, Any] | None:
        observation = env.observe()
        actionable = any(
            a["id"] == affordance_id and a["status"] != "blocked"
            for a in observation["affordances"]
        )
        if not actionable:
            return None
        return env.step(affordance_id, observation["observation_id"], rationale=rationale)

    for _ in range(max_turns):
        observation = env.observe()
        elapsed = _days(observation["world"]["date"]) - _days(start)
        if elapsed >= target_days:
            stop_reason = "target_reached"
            break
        if observation["world"]["pending_event"]:
            if resolved >= max_event_resolutions:
                stop_reason = "event_budget_exhausted"
                break
            resolution = resolve_pending_event(env, game_dir, checkpoint_save)
            if resolution["status"] in {"window_closed", "no_pending_event"}:
                continue  # window-close marker race
            if resolution["status"] != "identified":
                stop_reason = resolution["status"]
                break
            index, why = choose_option(resolution["options"])
            result = step(
                f"event_option.select#{index}",
                f"Event {resolution['event_key']}: {why}",
            )
            if not result or result["status"] != "executed":
                stop_reason = "selection_failed"
                break
            resolved += 1
            time.sleep(2)
            continue
        remaining = target_days - elapsed
        wait_id = "wait.90" if remaining >= 90 else "wait.30" if remaining >= 30 else "wait.7"
        step(wait_id, f"+{elapsed}/{target_days} days; {remaining} remain — time is the milestone path.")

    final = env.observe()
    return {
        "stop_reason": stop_reason,
        "events_resolved": resolved,
        "final_date": final["world"]["date"],
        "elapsed_days": _days(final["world"]["date"]) - _days(start),
        "score": final["score"],
    }
