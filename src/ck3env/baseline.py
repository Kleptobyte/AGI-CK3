"""Scripted baseline policies and the unattended soak loop.

Baselines are a release gate (docs/architecture.md): a benchmark that cannot show
LLMs beating a seeded random policy proves nothing. The baseline is also
the soak driver: it must respect lifecycle gates exactly like any agent —
live_proven families fully, probeable families probe-verb only — so a soak
run produces honest failure-taxonomy data, not gate noise.
"""
from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import Any

from .env import CK3Env

# Family weights: instrumentation kept rare so the soak spends its steps on
# gameplay surface. Checkpoint is additionally rate-limited below (135 MB
# saves; fixed name overwrites, but each write costs ~6 s).
FAMILY_WEIGHTS = {
    "pulse": 0.6,
    "checkpoint": 0.15,
    "wait": 1.0,
    "decision": 1.0,
    "gift": 0.7,
    "move_camp": 0.4,
}
CHECKPOINT_MIN_INTERVAL = 20  # steps between checkpoint.save picks


class RandomBaseline:
    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)
        self.steps_since_checkpoint = CHECKPOINT_MIN_INTERVAL

    def eligible(self, affordance: dict[str, Any]) -> bool:
        if affordance["status"] == "blocked":
            return False
        lifecycle = affordance.get("lifecycle")
        if lifecycle == "live_proven" or lifecycle == "certified":
            return True
        if lifecycle == "probeable":
            return ".probe" in affordance["id"]
        return False

    def choose(self, observation: dict[str, Any]) -> str | None:
        candidates = [a for a in observation["affordances"] if self.eligible(a)]
        if self.steps_since_checkpoint < CHECKPOINT_MIN_INTERVAL:
            candidates = [a for a in candidates if a["family"] != "checkpoint"]
        if not candidates:
            return None
        weights = [FAMILY_WEIGHTS.get(a["family"], 0.5) for a in candidates]
        pick = self.rng.choices(candidates, weights=weights, k=1)[0]
        if pick["family"] == "checkpoint":
            self.steps_since_checkpoint = 0
        else:
            self.steps_since_checkpoint += 1
        return pick["id"]


def run_soak(
    env: CK3Env,
    policy: RandomBaseline,
    max_steps: int,
    report_path: Path,
) -> dict[str, Any]:
    started = time.monotonic()
    latencies: list[float] = []
    statuses: dict[str, int] = {}
    families: dict[str, int] = {}
    stop_reason = "max_steps"
    first_date = last_date = None
    steps_run = 0

    for _ in range(max_steps):
        observation = env.observe()
        date = observation["world"]["date"]
        first_date = first_date or date
        last_date = date or last_date

        affordance_id = policy.choose(observation)
        if affordance_id is None:
            stop_reason = "no_eligible_affordances"
            break
        record = env.step(affordance_id, observation["observation_id"])
        steps_run += 1
        status = record["status"]
        statuses[status] = statuses.get(status, 0) + 1
        families[affordance_id.split(".")[0]] = families.get(affordance_id.split(".")[0], 0) + 1
        if record.get("latency_ms"):
            latencies.append(record["latency_ms"])
        if status == "timeout":
            stop_reason = f"transport_{record.get('failure_class') or 'timeout'}"
            break

    latencies.sort()
    report = {
        "steps_run": steps_run,
        "max_steps": max_steps,
        "stop_reason": stop_reason,
        "statuses": statuses,
        "families": families,
        "latency_ms": {
            "p50": latencies[len(latencies) // 2] if latencies else None,
            "p95": latencies[int(len(latencies) * 0.95)] if latencies else None,
            "max": latencies[-1] if latencies else None,
        },
        "game_date_first": first_date,
        "game_date_last": last_date,
        "wall_seconds": round(time.monotonic() - started, 1),
        "interventions": 0,  # by construction; any human action voids the soak
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report
