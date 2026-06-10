"""Mod registration: point the game at the repo's mod tree.

CK3 discovers mods through registration files in `<user dir>/mod/`; the
`path=` field may reference any directory, so the repo checkout itself is
the installed mod — no copying, and GUI files regenerated in the repo are
picked up on the next game restart. Enabling the mod in a launcher
playset remains a manual, one-time step in the Paradox launcher.
"""
from __future__ import annotations

from pathlib import Path

MOD_NAME = "agi_ck3_eval"


def repo_mod_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "mods" / MOD_NAME


def register_mod(ck3_user_dir: Path, mod_dir: Path | None = None) -> Path:
    """Write `<user dir>/mod/agi_ck3_eval.mod` referencing `mod_dir`.
    Returns the registration file path. Idempotent."""
    source = (mod_dir or repo_mod_dir()).resolve()
    descriptor = source / "descriptor.mod"
    if not descriptor.exists():
        raise FileNotFoundError(f"not a CK3 mod directory (no descriptor.mod): {source}")
    target_dir = Path(ck3_user_dir) / "mod"
    target_dir.mkdir(parents=True, exist_ok=True)
    registration = target_dir / f"{MOD_NAME}.mod"
    body = descriptor.read_text().rstrip("\n")
    registration.write_text(f'{body}\npath="{source.as_posix()}"\n')
    return registration
