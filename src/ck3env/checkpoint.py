"""Checkpoint saves: ground truth at cadence N, never the per-step bus.

Debug-mode saves are zip containers (inner `gamestate`) or raw text;
autosaves are uncompressed (135 MB observed for a late-era campaign).
Here we only do targeted reads needed for
verification predicates; full-fidelity extraction belongs to the optional
sidecar (docs/architecture.md) and is deliberately NOT reimplemented in Python.
"""
from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

_DATE_RE = re.compile(rb"(?:meta_date|date)=\"?([0-9]{1,4}\.[0-9]{1,2}\.[0-9]{1,2})")


class DeferredVerifier(NotImplementedError):
    """Raised for verifier predicates that land with their family's mod
    branch (M2). Catching this is a lifecycle gate, not an error path."""


def read_save_payload(path: Path, limit_bytes: int | None = None) -> bytes:
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for name in ("gamestate", "meta"):
                try:
                    with archive.open(name) as handle:
                        return handle.read(limit_bytes) if limit_bytes else handle.read()
                except KeyError:
                    continue
            raise ValueError(f"no gamestate/meta member in {path.name}")
    with path.open("rb") as handle:
        return handle.read(limit_bytes) if limit_bytes else handle.read()


def save_date(path: Path) -> str | None:
    # The date appears in the first kilobytes of both container layouts.
    head = read_save_payload(path, limit_bytes=1 << 20)
    match = _DATE_RE.search(head)
    return match.group(1).decode() if match else None


def save_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class SaveRecord:
    path: str
    name: str
    bytes: int
    sha256: str
    date: str | None


def describe_save(path: Path) -> SaveRecord:
    return SaveRecord(
        path=str(path),
        name=path.name,
        bytes=path.stat().st_size,
        sha256=save_digest(path),
        date=save_date(path),
    )


def _date_tuple(value: str) -> tuple[int, int, int]:
    year, month, day = (int(part) for part in value.split("."))
    return year, month, day


def date_advanced(before: str, after: str) -> bool:
    return _date_tuple(after) > _date_tuple(before)


# Verifier predicates keyed by registry.Family.verifier. Implemented ones
# operate on (save_record, context); the rest land with their families.
def _verify_save_exists(record: SaveRecord, context: dict) -> bool:
    return record.bytes > 0


def _verify_date_advanced(record: SaveRecord, context: dict) -> bool:
    before = context.get("date_before")
    if not before or not record.date:
        raise DeferredVerifier("date_advanced requires date_before and a readable save date")
    return date_advanced(before, record.date)


def _deferred(name: str):
    def _raise(record: SaveRecord, context: dict) -> bool:
        raise DeferredVerifier(
            f"verifier '{name}' lands with its family's certification"
        )
    return _raise


VERIFIERS = {
    "save_exists": _verify_save_exists,
    "date_advanced": _verify_date_advanced,
    "telemetry_marker": _deferred("telemetry_marker"),
    "camp_moved": _deferred("camp_moved"),
    "interaction_executed": _deferred("interaction_executed"),
    "contract_accepted": _deferred("contract_accepted"),
    "decision_taken": _deferred("decision_taken"),
    "focus_selected": _deferred("focus_selected"),
    "war_started": _deferred("war_started"),
    "marriage_arranged": _deferred("marriage_arranged"),
    "guardian_assigned": _deferred("guardian_assigned"),
    "alliance_formed": _deferred("alliance_formed"),
    "event_consumed": _deferred("event_consumed"),
}


# --- pending-event identity (targeted save + game-file reads) ---------------

def _balanced(payload: bytes, start: int) -> tuple[int, int] | None:
    open_at = payload.find(b"{", start)
    if open_at < 0:
        return None
    depth, in_quote = 0, False
    for index in range(open_at, len(payload)):
        ch = payload[index]
        if in_quote:
            in_quote = ch != 34
        elif ch == 34:
            in_quote = True
        elif ch == 123:
            depth += 1
        elif ch == 125:
            depth -= 1
            if depth == 0:
                return open_at, index + 1
    return None


def _field_int(block: bytes, key: bytes) -> int | None:
    match = re.search(rb"(?m)^\s*" + key + rb"\s*=\s*(\d+)", block)
    return int(match.group(1)) if match else None


def _field_name(block: bytes, key: bytes) -> str | None:
    match = re.search(rb"(?m)^\s*" + key + rb"\s*=\s*\"?([A-Za-z0-9_.]+)\"?", block)
    return match.group(1).decode() if match else None


def played_character_id(payload: bytes) -> int | None:
    match = re.search(rb"currently_played_characters=\{\s*(\d+)", payload)
    return int(match.group(1)) if match else None


def pending_player_events(save_path: Path) -> list[dict]:
    """Front-of-queue first. Each entry: event_key, save_event_id, character.
    Option metadata comes from the game's event definitions, not the save."""
    payload = read_save_payload(save_path)
    player = played_character_id(payload)
    events: list[dict] = []
    for match in re.finditer(rb"(?m)^player_event=\{", payload):
        bounds = _balanced(payload, match.start())
        if bounds is None:
            continue
        block = payload[bounds[0]:bounds[1]]
        character = _field_int(block, b"character")
        if player is not None and character != player:
            continue
        events.append({
            "event_key": _field_name(block, b"event"),
            "save_event_id": _field_int(block, b"id"),
            "character": character,
        })
    return events


def _has_toplevel_trigger(option_block: bytes) -> bool:
    """Only an option-level `trigger` hides the option (shifting later
    display indices); nested triggers inside tooltips/effects do not."""
    depth = 0
    for match in re.finditer(rb"(?m)^(\s*)(trigger\s*=\s*\{)|(\{)|(\})", option_block):
        token = match.group(0).strip()
        if token.endswith(b"{") and token.startswith(b"trigger") and depth == 1:
            return True
        depth += token.count(b"{") - token.count(b"}")
    return False


def event_options_from_game(event_key: str, game_dir: Path) -> list[dict]:
    """Parse the event definition for option labels and index stability.

    Display order equals definition order, but options with `trigger`
    blocks vanish when invalid — shifting every later index. An index is
    therefore stable only if no option at or before it is triggered.
    Unstable indices must never be armed (the GUI matches by index)."""
    needle = re.compile(rb"(?m)^" + re.escape(event_key).encode() + rb"\s*=\s*\{")
    roots = [game_dir / "events"]
    roots += sorted((game_dir / "dlc").glob("*/events")) if (game_dir / "dlc").exists() else []
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.txt")):
            data = path.read_bytes()
            match = needle.search(data)
            if not match:
                continue
            bounds = _balanced(data, match.start())
            if bounds is None:
                continue
            block = data[bounds[0]:bounds[1]]
            options: list[dict] = []
            any_triggered = False
            for opt_match in re.finditer(rb"(?m)^\s*option\s*=\s*\{", block):
                opt_bounds = _balanced(block, opt_match.start())
                if opt_bounds is None:
                    continue
                opt = block[opt_bounds[0]:opt_bounds[1]]
                if _has_toplevel_trigger(opt):
                    any_triggered = True
                options.append({
                    "index": len(options) + 1,
                    "label": _field_name(opt, b"name") or f"option_{len(options) + 1}",
                    "stable": not any_triggered,
                })
            return options
    return []
