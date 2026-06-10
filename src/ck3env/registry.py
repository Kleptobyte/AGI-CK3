"""Action-family registry: the single source of truth for the v3 surface.

Every layer derives from this table — request compilation, affordance
assembly, validation, the certification gauntlet, and the public claim
table. Adding a family means adding one row here plus one mod dispatch
branch (docs/architecture.md). Nothing else may hardcode family knowledge.

Lifecycle is claim hygiene: a family is "offline" until the certification
gauntlet proves it live, regardless of transport-level evidence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

LIFECYCLES = ("offline", "probeable", "live_proven", "certified")

AFFORDANCE_ID_RE = re.compile(
    r"^(?P<family>[a-z_]+)\.(?P<token>[a-z0-9_]+)(?:#(?P<slot>\d{1,2}))?$"
)

MAX_SLOTS = 16


@dataclass(frozen=True)
class Param:
    name: str
    kind: str  # "int" | "str"
    minimum: int | None = None
    maximum: int | None = None
    pattern: str | None = None

    def validate(self, value: object) -> str | None:
        if self.kind == "int":
            if not isinstance(value, int) or isinstance(value, bool):
                return f"{self.name} must be an integer"
            if self.minimum is not None and value < self.minimum:
                return f"{self.name} must be >= {self.minimum}"
            if self.maximum is not None and value > self.maximum:
                return f"{self.name} must be <= {self.maximum}"
            return None
        if not isinstance(value, str):
            return f"{self.name} must be a string"
        if self.pattern and not re.fullmatch(self.pattern, value):
            return f"{self.name} does not match {self.pattern}"
        return None


@dataclass(frozen=True)
class Family:
    id: str
    code: int                    # numeric action code written into mod vars
    verbs: tuple[str, ...]       # semantic verbs; first is probe when paired
    resolver: str                # "none" | "slot" | "allowlist:<name>"
    guard: str                   # CK3 trigger the mod rechecks ("" = none)
    verifier: str                # predicate id used by checkpoint verify
    lifecycle: str
    params: tuple[Param, ...] = ()
    variants: tuple[str, ...] = ()  # enumerated tokens (e.g. wait days)
    conduct: tuple[str, ...] = ()

    @property
    def paired(self) -> bool:
        return "probe" in self.verbs

    @property
    def execute_verb(self) -> str:
        return next(v for v in self.verbs if v != "probe")

    def tokens(self) -> tuple[str, ...]:
        return self.variants if self.variants else self.verbs


def _slot_param(name: str = "slot") -> Param:
    return Param(name, "int", 0, MAX_SLOTS - 1)


FAMILIES: tuple[Family, ...] = (
    Family("pulse", 1, ("refresh",), "none", "", "telemetry_marker", "live_proven"),
    Family("checkpoint", 2, ("save",), "none", "", "save_exists", "live_proven"),
    Family(
        "wait", 3, ("wait",), "none", "", "date_advanced", "live_proven",
        params=(Param("days", "int", 1, 365),),
        variants=("7", "30", "90"),
    ),
    Family(
        "move_camp", 4, ("probe", "move"), "slot",
        "is_character_interaction_valid:relocate_camp_to_interaction",
        "camp_moved", "live_proven",
    ),
    Family(
        "gift", 5, ("probe", "send"), "slot",
        "is_character_interaction_valid:gift_interaction",
        "interaction_executed", "probeable",
    ),
    Family(
        "task_contract", 6, ("probe", "accept"), "slot",
        "valid_laamp_basic_accept_only_trigger",
        "contract_accepted", "offline",
    ),
    Family(
        "decision", 7, ("probe", "take"), "allowlist:decisions",
        "can_execute_decision", "decision_taken", "live_proven",
        params=(Param("decision_id", "str", pattern=r"[a-z0-9_]{1,80}"),),
    ),
    Family(
        "lifestyle", 8, ("probe", "select"), "allowlist:focuses",
        "can_select_lifestyle_focus", "focus_selected", "offline",
        params=(Param("focus_id", "str", pattern=r"[a-z0-9_]{1,80}"),),
    ),
    # Ported v2 families, offline until their mod branches land and certify.
    Family(
        "war", 9, ("probe", "declare"), "slot",
        "can_declare_war", "war_started", "offline",
        conduct=("war_declared",),
    ),
    Family(
        "marriage", 10, ("probe", "arrange"), "slot",
        "is_character_interaction_valid:arrange_marriage_interaction",
        "marriage_arranged", "offline",
    ),
    Family(
        "education", 11, ("probe", "assign"), "slot",
        "is_character_interaction_valid:educate_child_interaction",
        "guardian_assigned", "offline",
    ),
    Family(
        "event_option", 13, ("select",), "event_index",
        "gui:EventOption.IsValid+!dangerous", "event_consumed", "offline",
        params=(Param("event_id", "int", 1, 10**9),),
    ),
    Family(
        "alliance", 12, ("probe", "negotiate"), "slot",
        "is_character_interaction_valid:negotiate_alliance_interaction",
        "alliance_formed", "offline",
    ),
)

ALLOWLISTS: dict[str, tuple[str, ...]] = {
    # Carried from v2 (docs/mod-owned-bridge-v2.md); each entry was already
    # vetted for guard + effect coverage.
    "decisions": (
        "change_election_candidacy_status_decision",
        "convert_to_local_culture_decision",
        "gather_provisions_decision",
        "go_fishing_decision",
        "invite_claimants_decision",
        "invite_knights_decision",
        "invite_poets_decision",
        "reform_carolingian_empire_decision",
        "restore_holy_roman_empire_decision",
        "scrape_the_barrel_decision",
        "hold_court_decision",
        "train_for_tournament_decision",
        "visit_local_settlement_decision",
        "zealous_missionary_prep_decision",
        "zealous_missionary_start_decision",
    ),
    # Deferred: populated from common/focuses at install time (focus ids must be
    # read from the pinned game version, not hardcoded).
    "focuses": (),
}

_BY_ID = {family.id: family for family in FAMILIES}
_BY_CODE = {family.code: family for family in FAMILIES}


def get(family_id: str) -> Family:
    family = _BY_ID.get(family_id)
    if family is None:
        raise KeyError(f"unknown action family: {family_id}")
    return family


def by_code(code: int) -> Family:
    family = _BY_CODE.get(code)
    if family is None:
        raise KeyError(f"unknown action code: {code}")
    return family


@dataclass(frozen=True)
class ParsedAffordance:
    family: Family
    verb: str
    variant: str | None
    slot: int | None

    @property
    def affordance_id(self) -> str:
        token = self.variant if self.variant is not None else self.verb
        suffix = f"#{self.slot}" if self.slot is not None else ""
        return f"{self.family.id}.{token}{suffix}"


def parse_affordance_id(affordance_id: str) -> ParsedAffordance:
    match = AFFORDANCE_ID_RE.fullmatch(affordance_id)
    if not match:
        raise ValueError(f"malformed affordance_id: {affordance_id}")
    family = get(match["family"])
    token = match["token"]
    slot = int(match["slot"]) if match["slot"] is not None else None

    if family.variants and token in family.variants:
        verb, variant = family.verbs[0], token
    elif token in family.verbs:
        verb, variant = token, None
    else:
        raise ValueError(
            f"{family.id} has no verb or variant '{token}'; "
            f"known: {', '.join(family.tokens())}"
        )

    if family.resolver == "slot":
        if slot is None:
            raise ValueError(f"{family.id} affordances require a #slot")
        if not 0 <= slot < MAX_SLOTS:
            raise ValueError(f"slot must be 0..{MAX_SLOTS - 1}")
    elif family.resolver == "event_index":
        if slot is None or not 1 <= slot <= 13:
            raise ValueError(f"{family.id} requires #<option-index 1..13>")
    elif family.resolver.startswith("allowlist:"):
        # The slot IS the allowlist index — one unique affordance id per
        # allowlisted value, same machinery as mod-published slots.
        allowlist = ALLOWLISTS[family.resolver.split(":", 1)[1]]
        if slot is None:
            raise ValueError(f"{family.id} affordances require #<allowlist-index>")
        if not 0 <= slot < len(allowlist):
            raise ValueError(
                f"{family.id} index {slot} out of range (allowlist has {len(allowlist)})"
            )
    elif slot is not None:
        raise ValueError(f"{family.id} affordances do not take a #slot")
    return ParsedAffordance(family, verb, variant, slot)


def validate_params(parsed: ParsedAffordance, params: dict[str, object]) -> list[str]:
    errors: list[str] = []
    family = parsed.family
    expected = {p.name for p in family.params}
    for key in params:
        if key not in expected:
            errors.append(f"unexpected parameter: {key}")
    slot_supplies_value = (
        family.resolver.startswith("allowlist:") and parsed.slot is not None
    )
    for spec in family.params:
        if parsed.variant is not None and spec.name == "days":
            continue  # variant supplies the value
        if spec.name not in params:
            if not slot_supplies_value:
                errors.append(f"missing parameter: {spec.name}")
            continue
        problem = spec.validate(params[spec.name])
        if problem:
            errors.append(problem)
    if family.resolver.startswith("allowlist:"):
        allowlist = ALLOWLISTS[family.resolver.split(":", 1)[1]]
        for spec in family.params:
            value = params.get(spec.name)
            if isinstance(value, str) and parsed.slot is not None:
                if allowlist and value != allowlist[parsed.slot]:
                    errors.append(
                        f"{spec.name} '{value}' does not match allowlist "
                        f"index {parsed.slot} ('{allowlist[parsed.slot]}')"
                    )
    return errors


def claim_table() -> list[dict[str, str]]:
    """Machine-readable proven/not-proven table; README generation reads this."""
    return [
        {"family": f.id, "lifecycle": f.lifecycle, "guard": f.guard or "none"}
        for f in FAMILIES
    ]
