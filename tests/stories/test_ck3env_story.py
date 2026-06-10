"""Story tests: correct infrastructure, proven wiring.

A SimulatedGame plays the mod's side of the wire protocol
against the REAL transport, env, observe, and compile code — request files
on disk, telemetry lines appended to a real log file, atomic handoff,
idempotent consumption, stale-observation rejection, lifecycle gating.
"""
from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from ck3env import compile as compiler
from ck3env import registry
from ck3env.env import CK3Env
from ck3env.observe import Snapshot
from ck3env.transport import (
    PULSE_REQUEST,
    AutoRunnerTransport,
    TransportState,
    write_request_atomic,
)

PROVENANCE = "[21:50:00][D][jomini_effect_impl.cpp:450]: file: run/agi3_request.txt line: 1: "


class SimulatedGame:
    """Consumes request files and emits protocol telemetry, like the mod."""

    def __init__(self, user_dir: Path, lose_first: bool = False,
                 ack_first_codes: set[int] = frozenset()):
        self.run_dir = user_dir / "run"
        self.log = user_dir / "logs" / "debug.log"
        self.lose_next = lose_first
        self.ack_first_codes = set(ack_first_codes)
        self.results: dict[int, str] = {}
        self.executions: dict[int, int] = {}
        self.invocations = 0
        self.pending_result: tuple[int, str] | None = None
        self.seq = 100

    def emit(self, payload: str) -> None:
        with self.log.open("a") as handle:
            handle.write(f"{PROVENANCE}agi3> v=1 {payload}\n")

    def tick(self, _seconds: float = 0.0) -> None:
        if self.pending_result is not None:  # wait/checkpoint completing
            req, line = self.pending_result
            self.pending_result = None
            self.results[req] = line
            self.emit(line)
            return
        request = self.run_dir / "agi3_request.txt"
        if not request.exists():
            return
        text = request.read_text()
        if "agi3_pulse = yes" in text:
            self.seq += 1
            self.emit(f"kind=hb seq={self.seq} req_last=0 date=1096.11.1 paused=yes")
            return
        match = re.search(r"name = agi3_req_id\n\tvalue = (\d+)", text)
        if not match:
            return
        self.invocations += 1
        req = int(match.group(1))
        if self.lose_next:  # lost handoff: file vanishes unconsumed, so
            self.lose_next = False  # only a true redelivery can recover
            request.unlink()
            return
        if req in self.results:  # consume-once: redelivery re-ACKs only
            self.emit(self.results[req])
            return
        self.executions[req] = self.executions.get(req, 0) + 1
        action = int(re.search(r"name = agi3_action\n\tvalue = (\d+)", text).group(1))
        verb_code = int(re.search(r"name = agi3_verb\n\tvalue = (\d+)", text).group(1))
        slot_match = re.search(r"name = agi3_slot\n\tvalue = (\d+)", text)
        family = registry.by_code(action).id
        verb = "probe" if verb_code == 1 else "execute"
        parts = [f"kind=result req={req} family={family} verb={verb}"]
        if slot_match:
            parts.append(f"slot={slot_match.group(1)}")
        if verb == "probe":
            parts.append("guard=ok")
        parts.append("status=executed")
        line = " ".join(parts)
        if action in self.ack_first_codes:
            self.emit(f"kind=ack req={req}")
            self.pending_result = (req, line)
        else:
            self.results[req] = line
            self.emit(line)


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def make_user_dir(root: Path) -> Path:
    user_dir = root / "ck3_user"
    (user_dir / "run").mkdir(parents=True)
    (user_dir / "logs").mkdir(parents=True)
    log = user_dir / "logs" / "debug.log"
    log.write_text(
        f"{PROVENANCE}agi3> v=1 kind=hb seq=1 req_last=0 date=1096.11.1 paused=yes\n"
        f"{PROVENANCE}agi3> v=1 kind=state date=1096.11.1 gold=12 landed=no\n"
        f"{PROVENANCE}agi3> v=1 kind=slot family=gift i=3 char=33643 ok=yes\n"
        f"{PROVENANCE}agi3> v=1 kind=slot family=war i=0 char=777 ok=yes\n"
    )
    return user_dir


class StoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="ck3env-story-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.root, ignore_errors=True))
        self.user_dir = make_user_dir(self.root)

    def make_env(self, name: str, **kwargs) -> CK3Env:
        env = CK3Env(self.root / name, ck3_user_dir=self.user_dir, **kwargs)
        return env

    def wire(self, env: CK3Env, sim: SimulatedGame) -> None:
        assert env._transport is not None
        env._transport.sleep = sim.tick  # the runner ticks while we wait

    def test_full_live_loop(self) -> None:
        sim = SimulatedGame(self.user_dir)
        env = self.make_env("live", live=True, allow_uncertified=True)
        self.wire(env, sim)

        observation = env.reset("story-task", seed=42)
        ids = {a["id"] for a in observation["affordances"]}
        self.assertIn("gift.probe#3", ids)
        self.assertNotIn("gift.send#3", ids)

        probe = env.step("gift.probe#3", observation["observation_id"])
        self.assertEqual(probe["status"], "executed", probe)
        self.assertIsNotNone(probe["latency_ms"])
        # At-rest pulse restored after every delivery.
        self.assertEqual(
            (self.user_dir / "run" / "agi3_request.txt").read_text(), PULSE_REQUEST
        )

        second = env.observe()
        self.assertIn("gift.send#3", {a["id"] for a in second["affordances"]})

        stale = env.step("gift.send#3", observation["observation_id"])
        self.assertEqual(stale["status"], "rejected")
        self.assertIn("stale", stale["blocker"])

        sent = env.step("gift.send#3", second["observation_id"])
        self.assertEqual(sent["status"], "executed", sent)

        final = env.observe()
        self.assertEqual(final["score"]["steps_total"], 3)
        self.assertEqual(final["score"]["steps_accepted"], 2)
        self.assertEqual(final["score"]["failures"]["agent_invalid"], 1)

    def test_lifecycle_gate_blocks_uncertified_live(self) -> None:
        env = self.make_env("gated", live=True)  # allow_uncertified defaults False
        self.wire(env, SimulatedGame(self.user_dir))
        observation = env.observe()
        offline = env.step("war.probe#0", observation["observation_id"])
        self.assertEqual(offline["status"], "rejected")
        self.assertIn("lifecycle=offline", offline["blocker"])
        # probeable family: probe passes the gate, execute does not
        SimulatedGame(self.user_dir).emit(
            "kind=result req=0 family=gift verb=probe slot=3 guard=ok status=executed"
        )
        observation = env.observe()
        execute = env.step("gift.send#3", observation["observation_id"])
        self.assertEqual(execute["status"], "rejected")
        self.assertIn("lifecycle=probeable", execute["blocker"])

    def test_dry_mode_compiles_without_game(self) -> None:
        env = CK3Env(self.root / "dry")  # no transport at all
        observation = env.observe()
        result = env.step("pulse.refresh", observation["observation_id"])
        self.assertEqual(result["status"], "compiled_dry")
        self.assertEqual(compiler.validate_request_text(result["request_text"]), [])

    def test_redelivery_is_idempotent(self) -> None:
        sim = SimulatedGame(self.user_dir, lose_first=True)
        clock = FakeClock()
        state = TransportState(self.root / "t" / "state.json")
        transport = AutoRunnerTransport(
            ck3_run_dir=self.user_dir / "run",
            log_path=self.user_dir / "logs" / "debug.log",
            state=state,
            clock=clock.now,
            sleep=lambda s: (clock.advance(0.1), sim.tick()),
        )
        snapshot = Snapshot()
        compiled = compiler.compile_request("gift.probe#3", {}, req_id=state.next_req_id())
        receipt = transport.deliver(
            compiled.text, compiled.req_id, snapshot,
            timeout_seconds=5.0, redeliver_after_seconds=0.15,
        )
        self.assertEqual(receipt.status, "acked")
        self.assertGreaterEqual(receipt.attempts, 2)  # we did redeliver
        self.assertEqual(sim.executions[compiled.req_id], 1)  # consumed once

    def test_ack_freezes_redelivery_until_result(self) -> None:
        sim = SimulatedGame(self.user_dir, ack_first_codes={registry.get("wait").code})
        clock = FakeClock()
        state = TransportState(self.root / "t2" / "state.json")
        transport = AutoRunnerTransport(
            ck3_run_dir=self.user_dir / "run",
            log_path=self.user_dir / "logs" / "debug.log",
            state=state,
            clock=clock.now,
            sleep=lambda s: (clock.advance(0.1), sim.tick()),
        )
        snapshot = Snapshot()
        compiled = compiler.compile_request("wait.30", {}, req_id=state.next_req_id())
        receipt = transport.deliver(
            compiled.text, compiled.req_id, snapshot,
            timeout_seconds=5.0, redeliver_after_seconds=0.15,
        )
        self.assertEqual(receipt.status, "acked")
        self.assertEqual(receipt.attempts, 1)  # ack suppressed redelivery
        self.assertEqual(sim.executions[compiled.req_id], 1)


if __name__ == "__main__":
    unittest.main()
