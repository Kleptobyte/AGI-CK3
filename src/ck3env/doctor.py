"""Setup diagnosis: every check returns ok/blocked with one exact reason."""
from __future__ import annotations

import json
import platform
import time
from pathlib import Path
from typing import Any

from . import registry
from .transport import runner_installed

DEFAULT_USER_DIR = Path.home() / "Documents" / "Paradox Interactive" / "Crusader Kings III"
REPO_MOD_DIR = Path(__file__).resolve().parents[2] / "mods" / "agi_ck3_eval"

# Common Steam install locations; doctor suggests the first that exists so
# next_steps are paste-ready, and falls back to a placeholder otherwise.
GAME_DIR_CANDIDATES = (
    Path.home() / "Library/Application Support/Steam/steamapps/common/Crusader Kings III/game",
    Path.home() / ".local/share/Steam/steamapps/common/Crusader Kings III/game",
    Path.home() / ".steam/steam/steamapps/common/Crusader Kings III/game",
)


def _check(ok: bool, blocker: str) -> dict[str, Any]:
    return {"ok": ok, "blocker": None if ok else blocker}


def _game_dir_guess() -> str:
    for candidate in GAME_DIR_CANDIDATES:
        if candidate.exists():
            return str(candidate)
    return "<CK3 install>/game"


def run(ck3_user_dir: Path | None = None) -> dict[str, Any]:
    user_dir = ck3_user_dir or DEFAULT_USER_DIR
    log_path = user_dir / "logs" / "debug.log"
    checks: dict[str, dict[str, Any]] = {}

    checks["user_dir"] = _check(user_dir.exists(), f"CK3 user dir missing: {user_dir}")
    checks["run_dir"] = _check(
        (user_dir / "run").exists(),
        "CK3 run/ dir missing; launch CK3 once with -debug_mode",
    )
    checks["debug_log"] = _check(log_path.exists(), "logs/debug.log missing; launch CK3 with -debug_mode")
    if log_path.exists():
        age = time.time() - log_path.stat().st_mtime
        checks["log_recent"] = _check(
            age < 3600, f"debug.log last written {age/60:.0f} min ago; is CK3 running?"
        )

    checks["mod_effects"] = _check(
        (REPO_MOD_DIR / "common" / "scripted_effects" / "agi3_bridge.txt").exists(),
        "agi3_bridge.txt missing from mod",
    )
    checks["mod_registered"] = _check(
        (user_dir / "mod" / "agi_ck3_eval.mod").exists(),
        "mod not registered with the game; run: python -m ck3env install-mod "
        f'--ck3-user-dir "{user_dir}" (then enable it in a launcher playset)',
    )
    checks["runner"] = _check(
        runner_installed(REPO_MOD_DIR / "gui"),
        "auto-runner not installed; see next_steps (then restart or `reload gui`)",
    )
    # Advisory, not a blocker: an empty allowlist degrades coverage (that
    # family advertises nothing) but the rig is fully playable without it.
    empty_allowlists = [name for name, values in registry.ALLOWLISTS.items() if not values]
    advisories = (
        [f"allowlists unpopulated: {', '.join(empty_allowlists)} — "
         "affected families advertise nothing until populated from the installed game"]
        if empty_allowlists else []
    )

    game_dir = _game_dir_guess()
    next_steps = [
        f'python -m ck3env install-mod --ck3-user-dir "{user_dir}"',
        f'python -m ck3env install-runner --game-gui-dir "{game_dir}/gui" '
        f'--mod-gui-dir "{REPO_MOD_DIR / "gui"}"',
        f'python -m ck3env install-event-gui --game-gui-dir "{game_dir}/gui" '
        f'--mod-gui-dir "{REPO_MOD_DIR / "gui"}"',
        "enable 'AGI CK3 Eval Harness' in a Paradox launcher playset",
        "launch CK3 with -debug_mode -develop, load a campaign, pause",
    ]

    ok = all(item["ok"] for item in checks.values())
    return {
        "ok": ok,
        "platform": platform.system(),
        "ck3_user_dir": str(user_dir),
        "game_dir_guess": game_dir,
        "checks": checks,
        "advisories": advisories,
        "next_steps": next_steps,
        "claim_table": registry.claim_table(),
    }


def main() -> int:
    report = run()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1
