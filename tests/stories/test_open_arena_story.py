"""Story: an external agent plays through the documented CLI surface only.

This is the AGENTS.md contract under test — reset with a submission,
observe/step with rationales, referee-closed episode, finalize, and an
offline rescore that reproduces the verdict from the bundle alone. No
library internals: every interaction goes through ck3env.cli.main."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from ck3env.cli import main as cli_main


def cli(*argv: str) -> dict:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = cli_main(list(argv))
    assert code == 0, f"cli {argv} exited {code}"
    return json.loads(buffer.getvalue())


class OpenArenaStoryTest(unittest.TestCase):
    def test_external_agent_loop_via_cli_only(self):
        run = str(Path(tempfile.mkdtemp(prefix="ck3env-arena-")) / "run")

        observation = cli(
            "reset", "--run", run, "--task", "smoke", "--seed", "7",
            "--agent-name", "story-agent", "--agent-model", "story-model",
            "--harness-notes", "first-available policy",
            "--max-steps", "5",
        )
        self.assertIn("observation_id", observation)
        self.assertEqual(observation["episode"]["budgets"]["max_steps"], 5)

        # The documented loop: observe, pick one available affordance, step
        # with the observation_id that produced it, repeat.
        recorded = 0
        while True:
            observation = cli("observe", "--run", run)
            available = [
                a for a in observation["affordances"] if a["status"] == "available"
            ]
            self.assertTrue(available, "an open episode must offer actions")
            result = cli(
                "step", "--run", run,
                available[0]["id"], observation["observation_id"],
                "--rationale", f"turn {recorded}: first available affordance",
            )
            if result["status"] == "refused":
                self.assertIn("budget_exhausted", result["blocker"])
                break
            self.assertEqual(result["status"], "compiled_dry")
            recorded += 1
            self.assertLessEqual(recorded, 5)
        self.assertEqual(recorded, 5)

        # Stale observation_id is rejected, refusal-style honesty throughout.
        report = cli("finalize", "--run", run)
        self.assertEqual(report["stop_reason"], "budget_exhausted")
        self.assertEqual(report["submission"]["agent_name"], "story-agent")
        self.assertEqual(report["score"]["steps_total"], 5)

        # Anyone can re-score the bundle offline; rationales ride along.
        verdict = cli("rescore", report["bundle"])
        self.assertEqual(verdict["score"], report["score"])
        self.assertEqual(verdict["stop_reason"], "budget_exhausted")
        self.assertEqual(verdict["submission"]["agent_model"], "story-model")

        import zipfile

        with zipfile.ZipFile(report["bundle"]) as archive:
            steps = [
                json.loads(line)
                for line in archive.read("steps.jsonl").decode().splitlines()
            ]
        self.assertTrue(all(s["rationale"] for s in steps))


if __name__ == "__main__":
    unittest.main()
