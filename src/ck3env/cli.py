"""Thin CLI over the environment API. One verb per call,
JSON out, no logic here that the library does not own."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import doctor
from .bundle import build as build_bundle
from .bundle import rescore
from .env import CK3Env
from .transport import install_runner


def _print(payload) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ck3env")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, *, run: bool = True, live_flags: bool = False):
        cmd = sub.add_parser(name)
        if run:
            cmd.add_argument("--run", type=Path, required=True)
        if live_flags:
            cmd.add_argument("--ck3-user-dir", type=Path, default=None)
            cmd.add_argument("--live", action="store_true")
            cmd.add_argument("--allow-uncertified", action="store_true")
        return cmd

    add("observe", live_flags=True)
    step = add("step", live_flags=True)
    step.add_argument("affordance_id")
    step.add_argument("observation_id")
    step.add_argument("--rationale", default=None)
    reset = add("reset", live_flags=True)
    reset.add_argument("--task", required=True)
    reset.add_argument("--seed", type=int, required=True)
    reset.add_argument("--agent-name", default=None)
    reset.add_argument("--agent-model", default=None)
    reset.add_argument("--harness-notes", default=None)
    reset.add_argument("--max-steps", type=int, default=None)
    reset.add_argument("--max-invalid-streak", type=int, default=None)
    reset.add_argument("--max-hours", type=float, default=None)
    add("score", live_flags=True)
    finalize_cmd = add("finalize", live_flags=True)
    finalize_cmd.add_argument("--reason", default="finalized")
    resolve_cmd = add("resolve-event", live_flags=True)
    resolve_cmd.add_argument("--game-dir", type=Path, required=True)
    resolve_cmd.add_argument("--checkpoint-save", type=Path, required=True)
    soak = add("baseline-run", live_flags=True)
    soak.add_argument("--steps", type=int, default=100)
    soak.add_argument("--seed", type=int, default=42)
    surv = add("survival-run", live_flags=True)
    surv.add_argument("--days", type=int, default=360)
    surv.add_argument("--game-dir", type=Path, required=True)
    surv.add_argument("--checkpoint-save", type=Path, required=True)
    bundle_cmd = add("bundle")
    bundle_cmd.add_argument("--sealed", action="store_true")
    rescore_cmd = sub.add_parser("rescore")
    rescore_cmd.add_argument("bundle_path", type=Path)
    doctor_cmd = sub.add_parser("doctor")
    doctor_cmd.add_argument("--ck3-user-dir", type=Path, default=None)
    mod_cmd = sub.add_parser("install-mod")
    mod_cmd.add_argument("--ck3-user-dir", type=Path, required=True)
    mod_cmd.add_argument("--mod-dir", type=Path, default=None)
    runner_cmd = sub.add_parser("install-runner")
    runner_cmd.add_argument("--game-gui-dir", type=Path, required=True)
    runner_cmd.add_argument("--mod-gui-dir", type=Path, required=True)
    evg_cmd = sub.add_parser("install-event-gui")
    evg_cmd.add_argument("--game-gui-dir", type=Path, required=True)
    evg_cmd.add_argument("--mod-gui-dir", type=Path, required=True)

    args = parser.parse_args(argv)

    if args.command == "doctor":
        report = doctor.run(args.ck3_user_dir)
        _print(report)
        return 0 if report["ok"] else 1
    if args.command == "rescore":
        _print(rescore(args.bundle_path))
        return 0
    if args.command == "install-mod":
        from .modinstall import register_mod

        registration = register_mod(args.ck3_user_dir, args.mod_dir)
        _print({
            "registered": str(registration),
            "next": "enable 'AGI CK3 Eval Harness' in a Paradox launcher playset, then launch with -debug_mode -develop",
        })
        return 0
    if args.command == "install-event-gui":
        from .eventgui import generate_event_windows

        written = generate_event_windows(args.game_gui_dir, args.mod_gui_dir)
        _print({"written": [str(path) for path in written]})
        return 0
    if args.command == "install-runner":
        target = install_runner(args.game_gui_dir, args.mod_gui_dir)
        _print({"installed": str(target)})
        return 0
    if args.command == "bundle":
        _print({"bundle": str(build_bundle(args.run, sealed=args.sealed))})
        return 0

    env = CK3Env(
        args.run,
        ck3_user_dir=getattr(args, "ck3_user_dir", None),
        live=getattr(args, "live", False),
        allow_uncertified=getattr(args, "allow_uncertified", False),
    )
    if args.command == "survival-run":
        from .episode import run_survival_episode

        report = run_survival_episode(
            env, target_days=args.days, game_dir=args.game_dir,
            checkpoint_save=args.checkpoint_save,
        )
        _print(report)
        return 0
    if args.command == "baseline-run":
        from .baseline import RandomBaseline, run_soak

        report = run_soak(
            env,
            RandomBaseline(args.seed),
            max_steps=args.steps,
            report_path=args.run / "soak_report.json",
        )
        _print(report)
        return 0
    if args.command == "resolve-event":
        from .identity import resolve_pending_event

        _print(resolve_pending_event(env, args.game_dir, args.checkpoint_save))
        return 0
    if args.command == "observe":
        _print(env.observe())
    elif args.command == "reset":
        budgets = {
            key: value
            for key, value in (
                ("max_steps", args.max_steps),
                ("max_invalid_streak", args.max_invalid_streak),
                ("max_hours", args.max_hours),
            )
            if value is not None
        }
        _print(
            env.reset(
                args.task,
                args.seed,
                budgets=budgets,
                submission={
                    "agent_name": args.agent_name,
                    "agent_model": args.agent_model,
                    "harness_notes": args.harness_notes,
                },
            )
        )
    elif args.command == "step":
        _print(env.step(args.affordance_id, args.observation_id, rationale=args.rationale))
    elif args.command == "finalize":
        _print(env.finalize(args.reason))
    elif args.command == "score":
        _print(env.observe()["score"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
