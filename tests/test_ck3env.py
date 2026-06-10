"""Unit gates for the ck3env v3 core. Line shapes mirror real game log output; the story test covers the wired loop."""
from __future__ import annotations

import unittest
import zipfile
from pathlib import Path

from ck3env import compile as compiler
from ck3env import checkpoint, registry, score
from ck3env.observe import LogTail, Snapshot, build_affordances, build_observation, parse_line
from ck3env.transport import RUNNER_SENTINEL, TransportError, generate_runner_gui

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "agi3"


class RegistryTests(unittest.TestCase):
    def test_parse_good_ids(self):
        cases = {
            "pulse.refresh": ("pulse", "refresh", None, None),
            "wait.30": ("wait", "wait", "30", None),
            "gift.probe#3": ("gift", "probe", None, 3),
            "gift.send#3": ("gift", "send", None, 3),
            "decision.take#7": ("decision", "take", None, 7),
        }
        for affordance_id, (family, verb, variant, slot) in cases.items():
            parsed = registry.parse_affordance_id(affordance_id)
            self.assertEqual(
                (parsed.family.id, parsed.verb, parsed.variant, parsed.slot),
                (family, verb, variant, slot),
            )
            self.assertEqual(parsed.affordance_id, affordance_id)

    def test_parse_rejections(self):
        for bad in ("gift.probe", "wait.13", "wait.30#2", "nope.x", "gift.probe#99",
                    "decision.take", "decision.take#15", "lifestyle.probe#0"):
            with self.assertRaises((ValueError, KeyError), msg=bad):
                registry.parse_affordance_id(bad)

    def test_codes_unique(self):
        codes = [family.code for family in registry.FAMILIES]
        self.assertEqual(len(codes), len(set(codes)))

    def test_lifecycles_match_gauntlet_evidence(self):
        live_proven = {"pulse", "checkpoint", "wait", "decision", "move_camp",
                       "event_option"}
        probeable = {"gift"}  # probes proven; execution awaits a qualifying state
        for family in registry.FAMILIES:
            self.assertIn(family.lifecycle, registry.LIFECYCLES)
            expected = ("live_proven" if family.id in live_proven
                        else "probeable" if family.id in probeable else "offline")
            self.assertEqual(
                family.lifecycle, expected,
                f"{family.id}: lifecycle changes only with gauntlet evidence",
            )


class CompileTests(unittest.TestCase):
    def test_request_only_invariant_holds(self):
        compiled = compiler.compile_request("gift.probe#3", {}, req_id=7)
        self.assertEqual(compiler.validate_request_text(compiled.text), [])
        self.assertIn("agi3_consume_effect = yes", compiled.text)
        self.assertEqual(compiled.variables["agi3_slot"], 3)
        self.assertEqual(compiled.variables["agi3_verb"], 1)

    def test_invariant_catches_gameplay_effects(self):
        compiled = compiler.compile_request("pulse.refresh", {}, req_id=1)
        tampered = compiled.text + "start_war = { casus_belli = claim_cb }\n"
        self.assertTrue(compiler.validate_request_text(tampered))

    def test_wait_variant_supplies_days(self):
        compiled = compiler.compile_request("wait.90", {}, req_id=2)
        self.assertEqual(compiled.variables["agi3_days"], 90)

    def test_decision_encoded_as_allowlist_index(self):
        decision = "restore_holy_roman_empire_decision"
        index = registry.ALLOWLISTS["decisions"].index(decision)
        compiled = compiler.compile_request(f"decision.take#{index}", {}, req_id=3)
        self.assertEqual(compiled.variables["agi3_slot"], index)
        self.assertNotIn(decision, compiled.text)  # strings never cross

    def test_decision_param_must_match_slot(self):
        with self.assertRaises(compiler.CompileError):
            compiler.compile_request(
                "decision.take#0", {"decision_id": "restore_holy_roman_empire_decision"}, 4
            )


class TelemetryTests(unittest.TestCase):
    def test_parse_real_provenance_line(self):
        raw = (
            "[21:45:40][D][jomini_effect_impl.cpp:450]: file: run/agi3_request.txt "
            "line: 1: agi3> v=1 kind=hb seq=41 req_last=6 date=1096.11.1 paused=yes"
        )
        event = parse_line(raw)
        assert event is not None
        self.assertEqual(event.kind, "hb")
        self.assertEqual(event.get_int("seq"), 41)
        self.assertEqual(event.get("date"), "1096.11.1")

    def test_date_engine_line_becomes_date_event(self):
        event = parse_line("[21:45:40][D][effectimpl.cpp:965]: DATE: yes - 1096.11.1")
        assert event is not None
        self.assertEqual(event.kind, "date")
        self.assertEqual(event.get("date"), "1096.11.1")

    def test_rejects_untagged_wrong_version_malformed(self):
        self.assertIsNone(parse_line("[21:45:40][D][x]: some other line"))
        self.assertIsNone(parse_line("x: agi3> v=0 kind=hb seq=1"))
        self.assertIsNone(parse_line("x: agi3> v=1 kind=hb broken token"))

    def test_log_tail_and_snapshot_on_fixture(self):
        tail = LogTail(FIXTURES / "debug_log_sample.txt")
        events = tail.read_new()
        snapshot = Snapshot()
        for event in events:
            snapshot.apply(event)
        self.assertEqual(snapshot.date, "1096.11.1")
        self.assertEqual(snapshot.paused, True)
        self.assertEqual(snapshot.world.get("gold"), "12")
        self.assertEqual(snapshot.slots["gift"][3]["char"], "33643")
        self.assertEqual(snapshot.slots["gift"][5]["ok"], "no")
        self.assertIn(0, snapshot.slots["move_camp"])  # family_code=4 decoded
        self.assertEqual(snapshot.probe_ok["gift"], {3})
        self.assertEqual(snapshot.conduct[0]["tag"], "imprisonment")
        self.assertEqual(tail.unparsed_tagged_lines, 2)  # v=0 and malformed
        self.assertEqual(tail.read_new(), [])  # offset advanced

    def test_snapshot_round_trip(self):
        tail = LogTail(FIXTURES / "debug_log_sample.txt")
        snapshot = Snapshot()
        for event in tail.read_new():
            snapshot.apply(event)
        restored = Snapshot.from_json(snapshot.to_json())
        self.assertEqual(restored.to_json(), snapshot.to_json())


class AffordanceTests(unittest.TestCase):
    def _snapshot(self) -> Snapshot:
        snapshot = Snapshot()
        snapshot.slots["gift"] = {
            3: {"family": "gift", "i": "3", "char": "33643", "ok": "yes"},
            5: {"family": "gift", "i": "5", "char": "16817638", "ok": "no"},
        }
        return snapshot

    def test_slot_families_advertise_only_published_ok_slots(self):
        ids = {a["id"] for a in build_affordances(self._snapshot())}
        self.assertIn("gift.probe#3", ids)
        self.assertNotIn("gift.probe#5", ids)
        self.assertNotIn("gift.send#3", ids)  # no successful probe yet

    def test_execute_appears_only_after_probe_ok(self):
        snapshot = self._snapshot()
        snapshot.probe_ok["gift"] = {3}
        ids = {a["id"] for a in build_affordances(snapshot)}
        self.assertIn("gift.send#3", ids)

    def test_blocked_probe_revokes_grant(self):
        from ck3env.observe import parse_line
        snapshot = self._snapshot()
        snapshot.probe_ok["gift"] = {3}
        line = ("x: agi3> v=1 kind=result req=9 family=gift verb=probe "
                "slot=3 guard=blocked status=executed")
        snapshot.apply(parse_line(line))
        ids = {a["id"] for a in build_affordances(snapshot)}
        self.assertNotIn("gift.send#3", ids)

    def test_front_event_blocks_gameplay_not_instrumentation(self):
        snapshot = self._snapshot()
        snapshot.probe_ok["gift"] = {3}
        snapshot.pending_event = {"event_id": "1001"}
        by_id = {a["id"]: a for a in build_affordances(snapshot)}
        self.assertEqual(by_id["gift.send#3"]["status"], "blocked")
        self.assertEqual(by_id["wait.30"]["status"], "blocked")
        self.assertEqual(by_id["pulse.refresh"]["status"], "available")
        self.assertEqual(by_id["checkpoint.save"]["status"], "available")

    def test_empty_allowlist_advertises_nothing(self):
        ids = {a["id"] for a in build_affordances(Snapshot())}
        self.assertFalse(
            any(i.startswith("lifestyle.") for i in ids),
            "empty focus allowlist must advertise nothing, never guess",
        )

    def test_observation_hash_changes_with_state(self):
        first = build_observation(self._snapshot(), {"step": 1}, {})
        snapshot = self._snapshot()
        snapshot.date = "1096.12.1"
        second = build_observation(snapshot, {"step": 1}, {})
        self.assertNotEqual(first["observation_id"], second["observation_id"])


class CheckpointTests(unittest.TestCase):
    def test_save_date_zip_and_raw(self):
        raw = b"SAV0102\nmeta_data={\nversion=1.16\nmeta_date=1096.12.1\n}\n"
        plain = Path(self._dir()) / "plain.ck3"
        plain.write_bytes(raw)
        self.assertEqual(checkpoint.save_date(plain), "1096.12.1")
        zipped = Path(self._dir()) / "zipped.ck3"
        with zipfile.ZipFile(zipped, "w") as archive:
            archive.writestr("gamestate", raw.decode())
        self.assertEqual(checkpoint.save_date(zipped), "1096.12.1")

    def test_date_advanced(self):
        self.assertTrue(checkpoint.date_advanced("1096.11.1", "1096.12.1"))
        self.assertFalse(checkpoint.date_advanced("1096.12.1", "1096.12.1"))

    def test_every_registry_verifier_exists(self):
        for family in registry.FAMILIES:
            self.assertIn(family.verifier, checkpoint.VERIFIERS, family.id)

    def _dir(self) -> str:
        import tempfile

        path = tempfile.mkdtemp(prefix="ck3env-test-")
        self.addCleanup(lambda: __import__("shutil").rmtree(path, ignore_errors=True))
        return path


class EventIdentityTests(unittest.TestCase):
    def test_pending_events_filtered_to_player(self):
        import tempfile
        save = (b"currently_played_characters={ 777 }\n"
                b"player_event={\n\tcharacter=999\n\tid=5\n\tevent=\"other.1\"\n}\n"
                b"player_event={\n\tcharacter=777\n\tid=9\n\tevent=\"flavor.2030\"\n}\n")
        p = Path(tempfile.mkdtemp(prefix="ck3env-evt-")) / "s.ck3"
        self.addCleanup(lambda: __import__("shutil").rmtree(p.parent, ignore_errors=True))
        p.write_bytes(save)
        events = checkpoint.pending_player_events(p)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_key"], "flavor.2030")
        self.assertEqual(events[0]["save_event_id"], 9)

    def test_option_stability_breaks_at_first_trigger(self):
        import tempfile
        game = Path(tempfile.mkdtemp(prefix="ck3env-game-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(game, ignore_errors=True))
        (game / "events").mkdir(parents=True)
        (game / "events" / "flavor.txt").write_bytes(
            b"namespace = flavor\nflavor.2030 = {\n"
            b"\toption = {\n\t\tname = flavor.2030.a\n\t}\n"
            b"\toption = {\n\t\ttrigger = { gold > 5 }\n\t\tname = flavor.2030.b\n\t}\n"
            b"\toption = {\n\t\tname = flavor.2030.c\n\t}\n}\n")
        options = checkpoint.event_options_from_game("flavor.2030", game)
        self.assertEqual([o["stable"] for o in options], [True, False, False])
        self.assertEqual(options[0]["label"], "flavor.2030.a")


class EpisodePolicyTests(unittest.TestCase):
    def test_choose_prefers_first_deliberate_safe(self):
        from ck3env.episode import choose_option
        index, why = choose_option([
            {"index": 1, "label": "a", "safe": False},
            {"index": 2, "label": "b", "safe": True},
        ])
        self.assertEqual(index, 2)
        self.assertIn("stable", why)

    def test_choose_falls_back_to_slot_one(self):
        from ck3env.episode import choose_option
        # An identity whose only safe entry is the slot-1 gamble.
        index, why = choose_option([
            {"index": 1, "label": "a", "safe": True, "gamble": True},
            {"index": 2, "label": "b", "safe": False},
        ])
        self.assertEqual(index, 1)
        self.assertIn("gamble", why)


class ScoreTests(unittest.TestCase):
    def test_ladder_from_published_primitives(self):
        snapshot = Snapshot()
        snapshot.date = "1099.1.5"
        snapshot.world.update({"gold": "82.4", "prestige": "140", "tier": "3", "hre": "0", "landless": "0"})
        snapshot.conduct.append({"tag": "imprisonment"})
        steps = [{"status": "executed"}, {"status": "rejected"}, {"status": "timeout"}]
        episode = {"start_date": "1097.12.20"}
        card = score.compute(snapshot, steps, episode)
        achieved = {m["id"] for m in card["ladder"] if m["achieved"]}
        self.assertEqual(achieved, {"survived_first_year", "landed_county", "duchy_tier"})
        self.assertEqual(card["ladder_points"], 30)
        self.assertEqual(card["indices"]["gold"], 82)
        self.assertEqual(card["indices"]["tier"], 3)
        self.assertIsNone(card["indices"]["dejure_hre_pct"])
        self.assertEqual(card["conduct"]["imprisonment"], 1)
        self.assertEqual(card["failures"]["agent_invalid"], 1)
        self.assertEqual(card["failures"]["transport_failure"], 1)
        self.assertEqual(card["steps_accepted"], 1)

    def test_landless_titular_tier_scores_no_land(self):
        snapshot = Snapshot()
        snapshot.world.update({"tier": "3", "landless": "1"})
        card = score.compute(snapshot, [], {})
        self.assertEqual(card["ladder_points"], 0)
        self.assertEqual(card["indices"]["tier"], 0)

    def test_survival_requires_full_year(self):
        snapshot = Snapshot()
        snapshot.date = "1098.11.1"
        card = score.compute(snapshot, [], {"start_date": "1098.1.2"})
        self.assertFalse(card["ladder"][0]["achieved"])
        self.assertEqual(card["ladder_points"], 0)


class BaselineTests(unittest.TestCase):
    def test_eligibility_respects_lifecycle(self):
        from ck3env.baseline import RandomBaseline
        policy = RandomBaseline(seed=1)
        self.assertTrue(policy.eligible(
            {"id": "wait.7", "family": "wait", "status": "available", "lifecycle": "live_proven"}))
        self.assertTrue(policy.eligible(
            {"id": "gift.probe#0", "family": "gift", "status": "probeable", "lifecycle": "probeable"}))
        self.assertFalse(policy.eligible(
            {"id": "gift.send#0", "family": "gift", "status": "available", "lifecycle": "probeable"}))
        self.assertFalse(policy.eligible(
            {"id": "war.probe#0", "family": "war", "status": "probeable", "lifecycle": "offline"}))
        self.assertFalse(policy.eligible(
            {"id": "wait.7", "family": "wait", "status": "blocked", "lifecycle": "live_proven"}))

    def test_dry_soak_runs_and_reports(self):
        import tempfile
        from ck3env.baseline import RandomBaseline, run_soak
        from ck3env.env import CK3Env
        root = Path(tempfile.mkdtemp(prefix="ck3env-soak-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        env = CK3Env(root / "run")
        report = run_soak(env, RandomBaseline(seed=7), max_steps=5,
                          report_path=root / "run" / "soak_report.json")
        self.assertEqual(report["steps_run"], 5)
        self.assertEqual(report["stop_reason"], "max_steps")
        self.assertEqual(set(report["statuses"]), {"compiled_dry"})
        self.assertTrue((root / "run" / "soak_report.json").exists())


class RunnerGenTests(unittest.TestCase):
    VANILLA = (
        "widget = {\n\tsize = { 100% 100% }\n"
        '\tname = "meta_info"\n\tvisible = "[IsDefaultGUIMode]"\n'
        "\t### children\n}\n"
    )

    def test_injects_sentinel_trigger_and_command(self):
        generated = generate_runner_gui(self.VANILLA)
        self.assertIn(RUNNER_SENTINEL, generated)
        self.assertIn("trigger_on_create = yes", generated)
        self.assertIn("'run agi3_request.txt;run agi3_event_clear.txt'", generated)
        self.assertIn("alpha", generated)

    def test_layout_drift_fails_loudly(self):
        with self.assertRaises(TransportError):
            generate_runner_gui("window = { name = \"renamed_root\" }")


if __name__ == "__main__":
    unittest.main()
