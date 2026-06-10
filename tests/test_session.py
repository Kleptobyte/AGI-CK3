"""Referee session layer: budgets, stop reasons, refusal semantics,
finalize idempotency, and submission round-trip through bundle/rescore.
All dry-mode — the referee must enforce identically with no game attached."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ck3env.bundle import rescore
from ck3env.env import CK3Env
from ck3env.observe import Snapshot


def _fresh_run() -> Path:
    return Path(tempfile.mkdtemp(prefix="ck3env-session-")) / "run"


def _step_first_available(env: CK3Env) -> dict:
    observation = env.observe()
    affordance = next(
        a for a in observation["affordances"] if a["status"] == "available"
    )
    return env.step(affordance["id"], observation["observation_id"], rationale="test")


class BudgetTests(unittest.TestCase):
    def test_max_steps_closes_episode_and_refuses_further_steps(self):
        env = CK3Env(_fresh_run())
        env.reset("t", seed=1, budgets={"max_steps": 2})
        self.assertEqual(_step_first_available(env)["status"], "compiled_dry")
        self.assertEqual(_step_first_available(env)["status"], "compiled_dry")
        episode = json.loads((env.run_dir / "episode.json").read_text())
        self.assertEqual(episode["stop_reason"], "budget_exhausted")
        refused = _step_first_available(env)
        self.assertEqual(refused["status"], "refused")
        self.assertIn("budget_exhausted", refused["blocker"])
        # Refusals are not steps: the record count must not grow.
        steps = (env.run_dir / "steps.jsonl").read_text().splitlines()
        self.assertEqual(len(steps), 2)
        # Observation stays available so the agent can see the final state.
        self.assertIn("observation_id", env.observe())

    def test_invalid_streak_closes_as_agent_stall(self):
        env = CK3Env(_fresh_run())
        env.reset("t", seed=1, budgets={"max_invalid_streak": 2})
        env.observe()
        self.assertEqual(env.step("wait.7", "bogus")["status"], "rejected")
        self.assertEqual(env.step("wait.7", "bogus")["status"], "rejected")
        episode = json.loads((env.run_dir / "episode.json").read_text())
        self.assertEqual(episode["stop_reason"], "agent_stall")
        self.assertEqual(env.step("wait.7", "bogus")["status"], "refused")

    def test_valid_step_resets_invalid_streak(self):
        env = CK3Env(_fresh_run())
        env.reset("t", seed=1, budgets={"max_invalid_streak": 2})
        env.observe()
        env.step("wait.7", "bogus")
        _step_first_available(env)
        env.step("wait.7", "bogus")
        episode = json.loads((env.run_dir / "episode.json").read_text())
        self.assertIsNone(episode["stop_reason"])

    def test_wall_clock_breach_refuses_before_any_work(self):
        env = CK3Env(_fresh_run())
        env.reset("t", seed=1, budgets={"max_hours": 1e-9})
        observation = env.observe()
        refused = env.step("wait.7", observation["observation_id"])
        self.assertEqual(refused["status"], "refused")
        self.assertIn("wall_clock", refused["blocker"])
        self.assertFalse((env.run_dir / "steps.jsonl").exists())


class FinalizeTests(unittest.TestCase):
    def test_finalize_idempotent_and_preserves_referee_stop_reason(self):
        env = CK3Env(_fresh_run())
        env.reset("t", seed=1, budgets={"max_invalid_streak": 1})
        env.observe()
        env.step("wait.7", "bogus")  # closes as agent_stall
        first = env.finalize()
        second = env.finalize(reason="something_else")
        self.assertEqual(first["stop_reason"], "agent_stall")
        self.assertEqual(second["stop_reason"], "agent_stall")
        self.assertTrue(Path(first["bundle"]).exists())

    def test_finalize_on_abandoned_run_stamps_reason(self):
        env = CK3Env(_fresh_run())
        env.reset("t", seed=1)
        report = env.finalize(reason="abandoned")
        self.assertEqual(report["stop_reason"], "abandoned")
        self.assertTrue(Path(report["bundle"]).exists())


class SubmissionRoundTripTests(unittest.TestCase):
    def test_submission_flows_reset_to_report_to_rescore(self):
        env = CK3Env(_fresh_run())
        env.reset(
            "t",
            seed=1,
            submission={
                "agent_name": "test-agent",
                "agent_model": "test-model",
                "harness_notes": "rolling window of 5",
            },
        )
        _step_first_available(env)
        report = env.finalize()
        self.assertEqual(report["submission"]["agent_name"], "test-agent")
        verdict = rescore(Path(report["bundle"]))
        self.assertEqual(verdict["submission"]["agent_model"], "test-model")
        self.assertEqual(verdict["stop_reason"], "finalized")
        self.assertEqual(verdict["score"], report["score"])

    def test_rescore_reproduces_date_derived_milestones(self):
        # Regression: rescore without the episode document silently lost
        # survived_first_year. The bundle's episode must drive the ladder.
        run = _fresh_run()
        env = CK3Env(run)
        env.reset("t", seed=1)
        episode = json.loads((run / "episode.json").read_text())
        episode["start_date"] = "1066.1.1"
        (run / "episode.json").write_text(json.dumps(episode))
        snapshot = Snapshot()
        snapshot.date = "1067.1.2"
        (run / "snapshot.json").write_text(json.dumps(snapshot.to_json()))
        env = CK3Env(run)  # reload persisted state
        report = env.finalize()
        survived = {m["id"]: m["achieved"] for m in report["score"]["ladder"]}
        self.assertTrue(survived["survived_first_year"])
        verdict = rescore(Path(report["bundle"]))
        self.assertEqual(verdict["score"], report["score"])


class OnboardingTests(unittest.TestCase):
    def test_install_mod_registers_repo_tree(self):
        from ck3env.modinstall import register_mod, repo_mod_dir

        user_dir = Path(tempfile.mkdtemp(prefix="ck3env-userdir-"))
        registration = register_mod(user_dir)
        body = registration.read_text()
        self.assertIn('name="AGI CK3 Eval Harness"', body)
        self.assertIn(f'path="{repo_mod_dir().resolve().as_posix()}"', body)
        # Idempotent re-run.
        self.assertEqual(register_mod(user_dir), registration)

    def test_doctor_reports_registration_and_next_steps(self):
        from ck3env import doctor
        from ck3env.modinstall import register_mod

        user_dir = Path(tempfile.mkdtemp(prefix="ck3env-userdir-"))
        report = doctor.run(user_dir)
        self.assertFalse(report["checks"]["mod_registered"]["ok"])
        self.assertTrue(any("install-mod" in step for step in report["next_steps"]))
        register_mod(user_dir)
        self.assertTrue(doctor.run(user_dir)["checks"]["mod_registered"]["ok"])


if __name__ == "__main__":
    unittest.main()
