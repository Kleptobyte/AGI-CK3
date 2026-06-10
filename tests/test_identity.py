"""Event identity: the referee publishes the FULL option set with honest
stability flags; the agent sees the genuine menu (unstable options as
blocked affordances) and the slot-1 gamble is explicit, never silent."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from ck3env.env import CK3Env
from ck3env.identity import identify_front_event
from ck3env.observe import Snapshot, build_affordances

SAVE = (
    b"currently_played_characters={ 777 }\n"
    b"player_event={\n\tcharacter=777\n\tid=9\n\tevent=\"flavor.2030\"\n}\n"
)


def _tmp(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


def _game_dir(events_body: bytes) -> Path:
    game = _tmp("ck3env-game-")
    (game / "events").mkdir(parents=True)
    (game / "events" / "flavor.txt").write_bytes(events_body)
    return game


class IdentifyFrontEventTests(unittest.TestCase):
    def _save(self) -> Path:
        directory = _tmp("ck3env-save-")
        self.addCleanup(lambda: shutil.rmtree(directory, ignore_errors=True))
        path = directory / "s.ck3"
        path.write_bytes(SAVE)
        return path

    def test_mixed_stability_keeps_true_flags(self):
        game = _game_dir(
            b"namespace = flavor\nflavor.2030 = {\n"
            b"\toption = {\n\t\tname = flavor.2030.a\n\t}\n"
            b"\toption = {\n\t\ttrigger = { gold > 5 }\n\t\tname = flavor.2030.b\n\t}\n"
            b"\toption = {\n\t\tname = flavor.2030.c\n\t}\n}\n"
        )
        self.addCleanup(lambda: shutil.rmtree(game, ignore_errors=True))
        identity = identify_front_event(self._save(), game)
        self.assertEqual(identity["event_key"], "flavor.2030")
        self.assertFalse(identity["all_gated"])
        flags = [(o["index"], o["safe"]) for o in identity["options"]]
        self.assertEqual(flags, [(1, True), (2, False), (3, False)])
        self.assertTrue(all("gamble" not in o for o in identity["options"]))

    def test_all_gated_marks_slot_one_gamble(self):
        game = _game_dir(
            b"namespace = flavor\nflavor.2030 = {\n"
            b"\toption = {\n\t\ttrigger = { gold > 5 }\n\t\tname = flavor.2030.a\n\t}\n"
            b"\toption = {\n\t\ttrigger = { gold > 9 }\n\t\tname = flavor.2030.b\n\t}\n}\n"
        )
        self.addCleanup(lambda: shutil.rmtree(game, ignore_errors=True))
        identity = identify_front_event(self._save(), game)
        self.assertTrue(identity["all_gated"])
        slot_one = next(o for o in identity["options"] if o["index"] == 1)
        self.assertTrue(slot_one["safe"])
        self.assertTrue(slot_one["gamble"])
        self.assertFalse(next(o for o in identity["options"] if o["index"] == 2)["safe"])

    def test_unparsed_event_synthesizes_gamble(self):
        game = _game_dir(b"namespace = flavor\n")
        self.addCleanup(lambda: shutil.rmtree(game, ignore_errors=True))
        identity = identify_front_event(self._save(), game)
        self.assertTrue(identity["all_gated"])
        self.assertEqual(len(identity["options"]), 1)
        self.assertTrue(identity["options"][0]["gamble"])

    def test_no_player_event_returns_none(self):
        directory = _tmp("ck3env-save-")
        self.addCleanup(lambda: shutil.rmtree(directory, ignore_errors=True))
        path = directory / "s.ck3"
        path.write_bytes(b"currently_played_characters={ 777 }\n")
        game = _game_dir(b"namespace = flavor\n")
        self.addCleanup(lambda: shutil.rmtree(game, ignore_errors=True))
        self.assertIsNone(identify_front_event(path, game))


class OptionAffordanceTests(unittest.TestCase):
    def test_full_menu_advertised_with_unstable_blocked(self):
        snapshot = Snapshot()
        snapshot.pending_event = {"present": "1"}
        identity = {
            "event_id": 9,
            "event_key": "flavor.2030",
            "options": [
                {"index": 1, "label": "a", "safe": True},
                {"index": 2, "label": "b", "safe": False},
            ],
            "all_gated": False,
        }
        selects = [
            a for a in build_affordances(snapshot, identity)
            if a["family"] == "event_option"
        ]
        by_id = {a["id"]: a for a in selects}
        self.assertEqual(by_id["event_option.select#1"]["status"], "available")
        self.assertEqual(by_id["event_option.select#2"]["status"], "blocked")
        self.assertIn("unstable", by_id["event_option.select#2"]["blockers"][0])

    def test_gamble_flag_rides_on_params(self):
        snapshot = Snapshot()
        snapshot.pending_event = {"present": "1"}
        identity = {
            "event_id": 9,
            "event_key": "flavor.2030",
            "options": [{"index": 1, "label": "a", "safe": True, "gamble": True}],
            "all_gated": True,
        }
        affordance = next(
            a for a in build_affordances(snapshot, identity)
            if a["id"] == "event_option.select#1"
        )
        self.assertEqual(affordance["status"], "available")
        self.assertTrue(affordance["params"]["gamble"])


class IdentityLifecycleTests(unittest.TestCase):
    def _env_with_pending_identity(self) -> CK3Env:
        run = _tmp("ck3env-idrun-") / "run"
        env = CK3Env(run)
        env.reset("t", seed=1)
        snapshot = Snapshot()
        snapshot.pending_event = {"present": "1"}
        (run / "snapshot.json").write_text(json.dumps(snapshot.to_json()))
        (run / "event_identity.json").write_text(json.dumps({
            "event_id": 9,
            "event_key": "flavor.2030",
            "options": [{"index": 1, "label": "a", "safe": True}],
            "all_gated": False,
        }))
        return CK3Env(run)  # reload persisted snapshot

    def test_selection_consumes_identity(self):
        env = self._env_with_pending_identity()
        observation = env.observe()
        result = env.step("event_option.select#1", observation["observation_id"])
        self.assertEqual(result["status"], "compiled_dry")
        self.assertFalse((env.run_dir / "event_identity.json").exists())

    def test_window_close_drops_stale_identity(self):
        env = self._env_with_pending_identity()
        snapshot = Snapshot()  # pending_event gone
        (env.run_dir / "snapshot.json").write_text(json.dumps(snapshot.to_json()))
        env = CK3Env(env.run_dir)
        observation = env.observe()
        self.assertFalse((env.run_dir / "event_identity.json").exists())
        self.assertFalse(
            [a for a in observation["affordances"] if a["family"] == "event_option"]
        )


if __name__ == "__main__":
    unittest.main()
