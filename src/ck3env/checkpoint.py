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
