"""CK3Env facade: the referee runs this loop; agents are
policies that receive the observation and return one affordance_id bound to
the observation_id that produced it. Stale bindings are rejected, one
in-flight request max, and offline-lifecycle families cannot step in live
mode — claim hygiene is enforced here, not in docs.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from . import __version__
from . import compile as compiler
from . import registry, score
from .observe import Snapshot, build_observation
from .transport import AutoRunnerTransport, TransportState


class Rejection(Exception):
    def __init__(self, blocker: str):
        super().__init__(blocker)
        self.blocker = blocker


class CK3Env:
    # Referee budgets: every episode ends with a recorded stop_reason no
    # matter how the driving agent behaves. Overridable at reset.
    DEFAULT_BUDGETS = {"max_steps": 200, "max_invalid_streak": 8, "max_hours": 6.0}

    def __init__(
        self,
        run_dir: Path,
        ck3_user_dir: Path | None = None,
        live: bool = False,
        allow_uncertified: bool = False,
    ):
        self.run_dir = Path(run_dir)
        self.live = live
        # Only the certification gauntlet sets this: it must execute
        # offline-lifecycle families in order to certify them.
        self.allow_uncertified = allow_uncertified
        self.ck3_user_dir = Path(ck3_user_dir) if ck3_user_dir else None
        if live and not self.ck3_user_dir:
            raise ValueError("live mode requires ck3_user_dir")
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._snapshot = self._load_snapshot()
        self._transport: AutoRunnerTransport | None = None
        if live and self.ck3_user_dir:
            self._transport = AutoRunnerTransport(
                ck3_run_dir=self.ck3_user_dir / "run",
                log_path=self.ck3_user_dir / "logs" / "debug.log",
                state=TransportState(self.run_dir / "transport_state.json"),
            )

    # -- persistence -------------------------------------------------------

    def _path(self, name: str) -> Path:
        return self.run_dir / name

    def _load_snapshot(self) -> Snapshot:
        path = self._path("snapshot.json")
        if path.exists():
            return Snapshot.from_json(json.loads(path.read_text()))
        return Snapshot()

    def _save_snapshot(self) -> None:
        self._path("snapshot.json").write_text(
            json.dumps(self._snapshot.to_json(), indent=2, sort_keys=True) + "\n"
        )

    def _episode(self) -> dict[str, Any]:
        path = self._path("episode.json")
        if path.exists():
            return json.loads(path.read_text())
        return {"task_id": None, "seed": None, "step": 0}

    def _save_episode(self, episode: dict[str, Any]) -> None:
        self._path("episode.json").write_text(
            json.dumps(episode, indent=2, sort_keys=True) + "\n"
        )

    def _steps(self) -> list[dict[str, Any]]:
        path = self._path("steps.jsonl")
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line]

    def _append_step(self, record: dict[str, Any]) -> None:
        with self._path("steps.jsonl").open("a") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    # -- environment API ----------------------------------------------------

    def reset(
        self,
        task_id: str,
        seed: int,
        budgets: dict[str, Any] | None = None,
        submission: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._save_episode(
            {
                "task_id": task_id,
                "seed": seed,
                "step": 0,
                "start_date": None,
                "budgets": {**self.DEFAULT_BUDGETS, **(budgets or {})},
                "started_at_epoch": time.time(),
                "steps_recorded": 0,
                "invalid_streak": 0,
                "stop_reason": None,
            }
        )
        declared = submission or {}
        self._path("submission.json").write_text(
            json.dumps(
                {
                    "agent_name": declared.get("agent_name") or "unspecified",
                    "agent_model": declared.get("agent_model") or "unspecified",
                    "harness_notes": declared.get("harness_notes") or "",
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        self._snapshot = Snapshot()
        self._save_snapshot()
        for name in (
            "steps.jsonl",
            "observation.json",
            "event_identity.json",
            "report.json",
        ):
            self._path(name).unlink(missing_ok=True)
        return self.observe()

    def observe(self) -> dict[str, Any]:
        if self._transport:
            self._transport.drain(self._snapshot)
            self._save_snapshot()
        episode = self._episode()
        if episode.get("start_date") is None and self._snapshot.date:
            episode["start_date"] = self._snapshot.date
            self._save_episode(episode)
        identity_path = self._path("event_identity.json")
        if self._snapshot.pending_event is None:
            # Identity is bound to the window it described; once the window
            # is gone its select affordances would be lies.
            identity_path.unlink(missing_ok=True)
        event_identity = (
            json.loads(identity_path.read_text()) if identity_path.exists() else None
        )
        observation = build_observation(
            self._snapshot,
            episode=episode,
            score=score.compute(self._snapshot, self._steps(), episode),
            event_identity=event_identity,
        )
        self._path("observation.json").write_text(
            json.dumps(observation, indent=2, sort_keys=True) + "\n"
        )
        return observation

    def legal_actions(self) -> list[dict[str, Any]]:
        return self.observe()["affordances"]

    def step(
        self, affordance_id: str, observation_id: str, rationale: str | None = None
    ) -> dict[str, Any]:
        started = time.monotonic()
        episode = self._episode()
        refusal = self._check_episode_open(episode)
        if refusal is not None:
            # A closed episode records no further agent activity: refusals
            # are returned, never appended to steps.jsonl.
            return refusal
        budgets = episode.get("budgets") or {}
        try:
            compiled, affordance = self._validate(affordance_id, observation_id)
        except Rejection as rejection:
            record = {
                "affordance_id": affordance_id,
                "status": "rejected",
                "blocker": rejection.blocker,
                "rationale": rationale,
            }
            self._append_step(record)
            episode["steps_recorded"] = int(episode.get("steps_recorded", 0)) + 1
            episode["invalid_streak"] = int(episode.get("invalid_streak", 0)) + 1
            self._stamp_stop_reason(episode, budgets)
            self._save_episode(episode)
            return record

        record: dict[str, Any] = {
            "affordance_id": compiled.affordance_id,
            "req_id": compiled.req_id,
            "observation_id": observation_id,
            "rationale": rationale,
        }
        if not self._transport:
            record.update({"status": "compiled_dry", "request_text": compiled.text})
        else:
            # Staged console verbs (tick/save) execute via Python keystrokes
            # after the mod acks; Python is the single non-idempotent actor.
            parsed = registry.parse_affordance_id(affordance_id)
            staged_plan = None
            if parsed.family.id == "wait":
                settle = {"7": 7.0, "30": 13.0, "90": 26.0}[parsed.variant]
                staged_plan = (f"tick_day {parsed.variant}", settle, "run agi3_after_tick.txt")
            elif parsed.family.id == "checkpoint":
                staged_plan = ("save agi3_checkpoint", 6.0, "run agi3_after_save.txt")
            timeout = 120.0 if staged_plan else 45.0
            receipt = self._transport.deliver(
                compiled.text, compiled.req_id, self._snapshot,
                timeout_seconds=timeout, staged_plan=staged_plan,
            )
            self._save_snapshot()
            record.update(
                {
                    "status": receipt.status if receipt.status != "acked" else "executed",
                    "latency_ms": receipt.latency_ms,
                    "attempts": receipt.attempts,
                    "result": receipt.result,
                    "failure_class": receipt.failure_class,
                }
            )
        record["elapsed_ms"] = round((time.monotonic() - started) * 1000, 1)
        parsed = registry.parse_affordance_id(compiled.affordance_id)
        if parsed.family.id == "event_option" and record["status"] != "rejected":
            # The selection consumed (or, dry, would consume) the window this
            # identity described.
            self._path("event_identity.json").unlink(missing_ok=True)
        episode["step"] += 1
        episode["steps_recorded"] = int(episode.get("steps_recorded", 0)) + 1
        episode["invalid_streak"] = 0
        self._stamp_stop_reason(episode, budgets)
        self._save_episode(episode)
        self._append_step(record)
        return record

    def finalize(self, reason: str = "finalized") -> dict[str, Any]:
        """Close the episode (if the referee has not already), score it, and
        build the proof bundle. Idempotent; safe on abandoned runs."""
        episode = self._episode()
        if not episode.get("stop_reason"):
            episode["stop_reason"] = reason
            self._save_episode(episode)
        observation = self.observe()
        submission_path = self._path("submission.json")
        report = {
            "harness_version": __version__,
            "stop_reason": episode["stop_reason"],
            "submission": (
                json.loads(submission_path.read_text())
                if submission_path.exists()
                else None
            ),
            "final_date": observation["world"]["date"],
            "score": observation["score"],
        }
        self._path("report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n"
        )
        from .bundle import build as build_bundle

        report["bundle"] = str(build_bundle(self.run_dir))
        return report

    # -- internals -----------------------------------------------------------

    def _check_episode_open(self, episode: dict[str, Any]) -> dict[str, Any] | None:
        """Refusal record if the episode is closed (or closes now on wall
        clock); None while the episode is open."""
        budgets = episode.get("budgets") or {}
        started = episode.get("started_at_epoch")
        max_hours = budgets.get("max_hours")
        if (
            not episode.get("stop_reason")
            and started
            and max_hours
            and time.time() - started > max_hours * 3600
        ):
            episode["stop_reason"] = "wall_clock"
            self._save_episode(episode)
        if episode.get("stop_reason"):
            return {
                "status": "refused",
                "blocker": (
                    f"episode complete (stop_reason={episode['stop_reason']}); "
                    "observe remains available, finalize builds the bundle"
                ),
            }
        return None

    def _stamp_stop_reason(self, episode: dict[str, Any], budgets: dict[str, Any]) -> None:
        if episode.get("stop_reason"):
            return
        max_streak = budgets.get("max_invalid_streak")
        if max_streak and int(episode.get("invalid_streak", 0)) >= int(max_streak):
            episode["stop_reason"] = "agent_stall"
            return
        max_steps = budgets.get("max_steps")
        if max_steps and int(episode.get("steps_recorded", 0)) >= int(max_steps):
            episode["stop_reason"] = "budget_exhausted"

    def _validate(
        self, affordance_id: str, observation_id: str
    ) -> tuple[compiler.CompiledRequest, dict[str, Any]]:
        observation_path = self._path("observation.json")
        if not observation_path.exists():
            raise Rejection("no observation exists; call observe() first")
        latest = json.loads(observation_path.read_text())
        if observation_id != latest.get("observation_id"):
            raise Rejection(
                f"stale observation_id {observation_id}; current is "
                f"{latest.get('observation_id')} — re-observe and re-decide"
            )
        affordance = next(
            (a for a in latest["affordances"] if a["id"] == affordance_id), None
        )
        if affordance is None:
            raise Rejection(f"affordance {affordance_id} is not in the current observation")
        if affordance["status"] == "blocked":
            raise Rejection(affordance["blockers"][0] if affordance["blockers"] else "blocked")

        parsed = registry.parse_affordance_id(affordance_id)
        if self.live and not self.allow_uncertified:
            lifecycle = parsed.family.lifecycle
            if lifecycle == "offline":
                raise Rejection(
                    f"family {parsed.family.id} is lifecycle=offline; it cannot "
                    f"run in live mode until the certification gauntlet proves it"
                )
            if lifecycle == "probeable" and parsed.verb != "probe":
                raise Rejection(
                    f"family {parsed.family.id} is lifecycle=probeable; only its "
                    f"probe verb is live-certified — execution awaits gauntlet proof"
                )
        expected = {p.name for p in parsed.family.params}
        params = {k: v for k, v in affordance.get("params", {}).items() if k in expected}
        if parsed.family.id == "event_option":
            params["event_id"] = int(affordance["params"]["event_id"])
        if self._transport:
            req_id = self._transport.state.next_req_id()
        else:
            episode = self._episode()
            req_id = int(episode["step"]) + 1
        try:
            compiled = compiler.compile_request(affordance_id, params, req_id)
        except compiler.CompileError as error:
            raise Rejection(str(error)) from error
        return compiled, affordance
