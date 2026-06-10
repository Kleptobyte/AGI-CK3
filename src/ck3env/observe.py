"""Telemetry bus parsing and observation assembly.

The mod emits ASCII key=value lines tagged [agi3] into debug.log
(docs/architecture.md). Measured write-to-log latency is ~200 ms p50. Line shape:

[21:45:40][D][jomini_effect_impl.cpp:450]: file: run/x.txt line: 1: [agi3] v=1 kind=hb ...

We locate the tag anywhere in the line; everything after it is the payload.
The observation document is a single canonical tree — every fact appears
exactly once, hashed for stale-action rejection (architecture.md).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import PROTOCOL_VERSION, TELEMETRY_TAG
from . import registry

OBSERVATION_SCHEMA = "obs.v3.0"


@dataclass(frozen=True)
class TelemetryEvent:
    kind: str
    fields: dict[str, str]
    raw: str

    def get(self, key: str, default: str | None = None) -> str | None:
        return self.fields.get(key, default)

    def get_int(self, key: str) -> int | None:
        value = self.fields.get(key)
        if value is None:
            return None
        try:
            return int(value)
        except ValueError:
            try:  # loc GetValue may render "5.0"-style decimals
                return int(float(value))
            except ValueError:
                return None


def _family_name(event: "TelemetryEvent") -> str | None:
    """Mod lines carry numeric family_code (loc strings cannot interpolate
    family names); the simulator and future mod versions may carry family=.
    Accept both, registry being the decoder ring."""
    name = event.fields.get("family")
    if name:
        return name
    code = event.get_int("family_code")
    if code is None:
        return None
    try:
        return registry.by_code(code).id
    except KeyError:
        return None


_DATE_LINE = re.compile(r"\]: DATE: yes - ([0-9]{1,4}\.[0-9]{1,2}\.[0-9]{1,2})\s*$")


def parse_line(raw: str) -> TelemetryEvent | None:
    tag_at = raw.find(TELEMETRY_TAG)
    if tag_at < 0:
        # Dates arrive via debug_log_date engine lines, not loc interpolation
        # (localization cannot render dates; the engine line can).
        date_match = _DATE_LINE.search(raw)
        if date_match:
            return TelemetryEvent(kind="date", fields={"date": date_match.group(1)}, raw=raw)
        return None
    payload = raw[tag_at + len(TELEMETRY_TAG):].strip()
    fields: dict[str, str] = {}
    for token in payload.split():
        if "=" not in token:
            return None  # malformed: fail closed, surface in unparsed count
        key, value = token.split("=", 1)
        fields[key] = value
    if fields.get("v") != str(PROTOCOL_VERSION):
        return None
    kind = fields.pop("kind", None)
    if not kind:
        return None
    return TelemetryEvent(kind=kind, fields=fields, raw=raw)


class LogTail:
    """Stateful offset reader over debug.log; survives session restarts."""

    def __init__(self, log_path: Path, offset: int = 0) -> None:
        self.log_path = log_path
        self.offset = offset
        self.unparsed_tagged_lines = 0

    def read_new(self) -> list[TelemetryEvent]:
        if not self.log_path.exists():
            return []
        size = self.log_path.stat().st_size
        if size < self.offset:  # new game session truncated the log
            self.offset = 0
        if size == self.offset:
            return []
        with self.log_path.open("rb") as handle:
            handle.seek(self.offset)
            chunk = handle.read(size - self.offset)
        # Only advance past the last complete line.
        last_newline = chunk.rfind(b"\n")
        if last_newline < 0:
            return []
        self.offset += last_newline + 1
        events: list[TelemetryEvent] = []
        for raw_line in chunk[: last_newline + 1].decode("utf-8", "replace").splitlines():
            event = parse_line(raw_line)
            if event is not None:
                events.append(event)
            elif TELEMETRY_TAG in raw_line:
                self.unparsed_tagged_lines += 1
        return events


@dataclass
class Snapshot:
    """Accumulated world view from telemetry; serializable between turns."""

    last_heartbeat_seq: int | None = None
    last_consumed_req: int | None = None
    date: str | None = None
    paused: bool | None = None
    world: dict[str, str] = field(default_factory=dict)
    slots: dict[str, dict[int, dict[str, str]]] = field(default_factory=dict)
    results: dict[int, dict[str, str]] = field(default_factory=dict)
    probe_ok: dict[str, set[int]] = field(default_factory=dict)
    conduct: list[dict[str, str]] = field(default_factory=list)
    pending_event: dict[str, str] | None = None

    def apply(self, event: TelemetryEvent) -> None:
        fields = event.fields
        if event.kind == "date":
            self.date = fields["date"]
        elif event.kind == "hb":
            self.last_heartbeat_seq = event.get_int("seq")
            self.last_consumed_req = event.get_int("req_last")
            self.date = fields.get("date", self.date)
            if "paused" in fields:
                self.paused = fields["paused"] == "yes"
        elif event.kind == "state":
            self.date = fields.get("date", self.date)
            self.world.update(
                {k: v for k, v in fields.items() if k not in {"date", "seq"}}
            )
        elif event.kind == "slot_clear":
            family = _family_name(event)
            if family:
                # Fresh publication: stale slots AND probe grants die here —
                # advertisement is only ever as old as the last refresh.
                self.slots.pop(family, None)
                self.probe_ok.pop(family, None)
        elif event.kind == "slot":
            family = _family_name(event)
            index = event.get_int("i")
            if family and index is not None:
                self.slots.setdefault(family, {})[index] = dict(fields)
        elif event.kind == "result":
            req = event.get_int("req")
            if req is not None:
                self.results[req] = dict(fields)
                self.last_consumed_req = max(self.last_consumed_req or 0, req)
            family = _family_name(event)
            verb = fields.get("verb") or (
                "probe" if event.get_int("verb_code") == 1 else "execute"
            )
            slot = event.get_int("slot")
            if family and verb == "probe" and slot is not None:
                if fields.get("guard") == "ok":
                    self.probe_ok.setdefault(family, set()).add(slot)
                else:
                    # A blocked probe REVOKES an earlier grant: the world
                    # moved (cooldown, cost, death) and advertising the
                    # execute verb would be a lie the mod guard then catches.
                    self.probe_ok.get(family, set()).discard(slot)
        elif event.kind == "conduct":
            self.conduct.append(dict(fields))
        elif event.kind == "event":
            if fields.get("present") == "0":
                self.pending_event = None
            else:
                self.pending_event = dict(fields) or None

    def to_json(self) -> dict[str, Any]:
        return {
            "last_heartbeat_seq": self.last_heartbeat_seq,
            "last_consumed_req": self.last_consumed_req,
            "date": self.date,
            "paused": self.paused,
            "world": self.world,
            "slots": {f: {str(i): s for i, s in by.items()} for f, by in self.slots.items()},
            "results": {str(r): v for r, v in self.results.items()},
            "probe_ok": {f: sorted(s) for f, s in self.probe_ok.items()},
            "conduct": self.conduct,
            "pending_event": self.pending_event,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Snapshot":
        snapshot = cls()
        snapshot.last_heartbeat_seq = data.get("last_heartbeat_seq")
        snapshot.last_consumed_req = data.get("last_consumed_req")
        snapshot.date = data.get("date")
        snapshot.paused = data.get("paused")
        snapshot.world = dict(data.get("world", {}))
        snapshot.slots = {
            f: {int(i): dict(s) for i, s in by.items()}
            for f, by in data.get("slots", {}).items()
        }
        snapshot.results = {int(r): dict(v) for r, v in data.get("results", {}).items()}
        snapshot.probe_ok = {f: set(v) for f, v in data.get("probe_ok", {}).items()}
        snapshot.conduct = list(data.get("conduct", []))
        snapshot.pending_event = data.get("pending_event")
        return snapshot


def build_affordances(
    snapshot: Snapshot, event_identity: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Derive the current affordance list purely from registry + snapshot.

    Slot families advertise exactly the slots the mod published (ok=yes);
    execute verbs appear only after a matching successful probe. Python
    never predicts resolvability.
    """
    affordances: list[dict[str, Any]] = []
    front_event = snapshot.pending_event is not None

    def add(affordance_id: str, family: registry.Family, status: str,
            blockers: list[str], params: dict[str, Any] | None = None) -> None:
        affordances.append(
            {
                "id": affordance_id,
                "family": family.id,
                "status": status,
                "blockers": blockers,
                "params": params or {},
                "lifecycle": family.lifecycle,
            }
        )

    if front_event and event_identity:
        family = registry.get("event_option")
        for option in event_identity.get("options", []):
            # The full menu is advertised; index-unstable options appear as
            # blocked so the agent sees the genuine choice set without being
            # able to arm a slot whose mapping may shift under it.
            safe = bool(option.get("safe"))
            params: dict[str, Any] = {
                "event_id": int(event_identity["event_id"]),
                "label": option.get("label", ""),
            }
            if option.get("gamble"):
                params["gamble"] = True
            affordances.append({
                "id": f"event_option.select#{int(option['index'])}",
                "family": family.id,
                "status": "available" if safe else "blocked",
                "blockers": [] if safe else [
                    "display index unstable: a trigger-gated option above "
                    "this slot may shift the mapping"
                ],
                "params": params,
                "lifecycle": family.lifecycle,
            })
    for family in registry.FAMILIES:
        if family.id == "event_option":
            continue  # handled above, identity-gated
        gameplay_blocked = (
            ["front event pending; resolve it before gameplay actions"]
            if front_event and family.id not in {"pulse", "checkpoint"}
            else []
        )
        if family.resolver == "none":
            for token in family.tokens():
                params = {"days": int(token)} if family.variants else {}
                status = "blocked" if gameplay_blocked else "available"
                add(f"{family.id}.{token}", family, status, gameplay_blocked, params)
        elif family.resolver.startswith("allowlist:"):
            allowlist = registry.ALLOWLISTS[family.resolver.split(":", 1)[1]]
            if not allowlist:
                continue  # not populated yet: advertise nothing, never guess
            param_name = family.params[0].name
            for index, value in enumerate(allowlist):
                status = "blocked" if gameplay_blocked else "probeable"
                add(f"{family.id}.probe#{index}", family, status,
                    gameplay_blocked, {param_name: value})
                if index in snapshot.probe_ok.get(family.id, set()):
                    exec_status = "blocked" if gameplay_blocked else "available"
                    add(f"{family.id}.{family.execute_verb}#{index}", family,
                        exec_status, gameplay_blocked, {param_name: value})
        else:  # slot
            published = snapshot.slots.get(family.id, {})
            for index, slot in sorted(published.items()):
                if slot.get("ok") != "yes":
                    continue
                probe_status = "blocked" if gameplay_blocked else "probeable"
                add(f"{family.id}.probe#{index}", family, probe_status,
                    gameplay_blocked, {k: v for k, v in slot.items()
                                       if k not in {"family", "i", "ok"}})
                if index in snapshot.probe_ok.get(family.id, set()):
                    exec_status = "blocked" if gameplay_blocked else "available"
                    add(f"{family.id}.{family.execute_verb}#{index}", family,
                        exec_status, gameplay_blocked)
    return affordances


def canonical_json(document: dict[str, Any]) -> str:
    return json.dumps(document, sort_keys=True, separators=(",", ":"))


def observation_id(document: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(document).encode()).hexdigest()[:16]


def build_observation(
    snapshot: Snapshot,
    episode: dict[str, Any],
    score: dict[str, Any],
    event_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    affordances = build_affordances(snapshot, event_identity)
    last_result = (
        snapshot.results.get(snapshot.last_consumed_req)
        if snapshot.last_consumed_req is not None
        else None
    )
    body = {
        "schema": OBSERVATION_SCHEMA,
        "episode": episode,
        "world": {
            "date": snapshot.date,
            "paused": snapshot.paused,
            "facts": snapshot.world,
            "pending_event": snapshot.pending_event,
        },
        "affordances": affordances,
        "last_step": (
            {"req_id": snapshot.last_consumed_req, **last_result}
            if last_result
            else None
        ),
        "score": score,
    }
    return {**body, "observation_id": observation_id(body)}
