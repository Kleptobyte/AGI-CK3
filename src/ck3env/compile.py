"""Request envelope compilation (docs/architecture.md).

A request is a CK3 run-file that sets agi3_* variables and calls exactly one
mod entrypoint. The v2 safety invariant is ported verbatim: generated
scripts contain ZERO gameplay effects — only numeric variable assignments
and the entrypoint call. validate_request_text() enforces this and is run
on every compile (and in tests against goldens).

String parameters never cross the boundary: allowlisted ids are encoded as
their registry allowlist index, exactly as v2 encoded decision ids.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import PROTOCOL_VERSION
from . import registry

ENTRYPOINT = "agi3_consume_effect"
PULSE_ENTRYPOINT = "agi3_pulse"

VERB_CODES = {"probe": 1, "execute": 2}

_HEADER = (
    "# agi3 request envelope (generated; request-only, no gameplay effects)\n"
)

_ALLOWED_LINE = re.compile(
    r"^(?:"
    r"|#.*"
    r"|set_variable = \{"
    r"|\tname = agi3_[a-z0-9_]+"
    r"|\tvalue = -?\d+"
    r"|\}"
    rf"|{ENTRYPOINT} = yes"
    rf"|{PULSE_ENTRYPOINT} = yes"
    r")$"
)


class CompileError(ValueError):
    pass


@dataclass(frozen=True)
class CompiledRequest:
    req_id: int
    affordance_id: str
    text: str
    variables: dict[str, int]


def _set_variable(name: str, value: int) -> str:
    return f"set_variable = {{\n\tname = {name}\n\tvalue = {value}\n}}\n"


def _encode_params(
    parsed: registry.ParsedAffordance, params: dict[str, object]
) -> dict[str, int]:
    family = parsed.family
    encoded: dict[str, int] = {}
    if parsed.variant is not None:
        encoded["agi3_days"] = int(parsed.variant)
    if parsed.slot is not None:
        encoded["agi3_slot"] = parsed.slot
    if family.resolver == "event_index":
        encoded["agi3_evt_event_id"] = int(params["event_id"])  # type: ignore[arg-type]
    if family.resolver.startswith("allowlist:"):
        # The affordance slot IS the allowlist index (registry guarantees
        # range); the string itself never crosses the boundary, and the slot
        # is echoed by mod result lines for uniform probe gating.
        encoded["agi3_slot"] = parsed.slot  # type: ignore[assignment]
    for spec in family.params:
        if spec.kind == "int" and spec.name in params and parsed.variant is None:
            encoded[f"agi3_{spec.name}"] = int(params[spec.name])  # type: ignore[arg-type]
    return encoded


def compile_request(
    affordance_id: str,
    params: dict[str, object],
    req_id: int,
) -> CompiledRequest:
    parsed = registry.parse_affordance_id(affordance_id)
    errors = registry.validate_params(parsed, params)
    if errors:
        raise CompileError("; ".join(errors))
    variables: dict[str, int] = {
        "agi3_protocol": PROTOCOL_VERSION,
        "agi3_req_id": req_id,
        "agi3_action": parsed.family.code,
        "agi3_verb": VERB_CODES["probe" if parsed.verb == "probe" else "execute"],
    }
    variables.update(_encode_params(parsed, params))

    lines = [_HEADER]
    for name, value in variables.items():
        lines.append(_set_variable(name, value))
    lines.append(f"{ENTRYPOINT} = yes\n")
    text = "".join(lines)

    problems = validate_request_text(text)
    if problems:  # defense in depth: the generator itself must stay honest
        raise CompileError("generated request violated invariant: " + "; ".join(problems))
    return CompiledRequest(req_id, parsed.affordance_id, text, variables)


def validate_request_text(text: str) -> list[str]:
    """The request-only invariant: nothing but agi3_* numeric variables and
    one entrypoint call may appear in a generated run file."""
    problems: list[str] = []
    entrypoints = 0
    for line_number, raw in enumerate(text.splitlines(), start=1):
        if not _ALLOWED_LINE.fullmatch(raw):
            problems.append(f"line {line_number} not request-only: {raw!r}")
        if raw == f"{ENTRYPOINT} = yes" or raw == f"{PULSE_ENTRYPOINT} = yes":
            entrypoints += 1
    if entrypoints != 1:
        problems.append(f"expected exactly one entrypoint call, found {entrypoints}")
    return problems
