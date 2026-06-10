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


def _check(ok: bool, blocker: str) -> dict[str, Any]:
    return {"ok": ok, "blocker": None if ok else blocker}


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
    checks["runner"] = _check(
        runner_installed(REPO_MOD_DIR / "gui"),
        "auto-runner not installed; run: ck3env install-runner (then restart or `reload gui`)",
    )
    empty_allowlists = [name for name, values in registry.ALLOWLISTS.items() if not values]
    checks["allowlists"] = _check(
        not empty_allowlists,
        f"allowlists unpopulated: {', '.join(empty_allowlists)} "
        f"(populated from the installed game at M2; affected families advertise nothing)",
    )

    ok = all(item["ok"] for item in checks.values())
    return {
        "ok": ok,
        "platform": platform.system(),
        "ck3_user_dir": str(user_dir),
        "checks": checks,
        "claim_table": registry.claim_table(),
    }


def main() -> int:
    report = run()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1
