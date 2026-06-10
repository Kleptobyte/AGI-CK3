"""Event-window GUI generation: per-option selector states regenerated
from the installed game's GUI sources for the current game version.

The selector is a zero-duration trigger_when state on each option button
that fires EventOption.Select only when the window is on top, the option
is valid and not dangerous-flagged, and the armed request's index matches
the option's own position. The scripted_gui consume-recorder closes the
protocol loop. Selection authority therefore stays inside the game's own
UI validity model; the harness merely arms an index.
"""
from __future__ import annotations

from pathlib import Path

EVENT_WINDOW_NAMES = (
    "big_event_window.gui",
    "character_event.gui",
    "duel_event.gui",
    "fullscreen_event.gui",
)
INSERT_TARGET = "button_eventoption = {}"
PATCH_SENTINEL = "agi_ck3_event_option_auto_select"

PATCH_STATE_LINES = (
    "# AGI-CK3 generated bridge: one-shot event option selector.",
    "state = {",
    "\tname = agi_ck3_event_option_auto_select",
    "\tduration = 0",
    "\ttrigger_when = \"[And( And( EventWindow.IsOnTop, EventOption.IsValid ), And( And( Not( EventOption.HasFlag('dangerous') ), Not( IsPauseMenuShown ) ), And( And( GreaterThan_CFixedPoint( GetPlayer.MakeScope.Var('agi_ck3_bridge_v2_request_id').GetValue, '(CFixedPoint)0' ), EqualTo_CFixedPoint( GetPlayer.MakeScope.Var('agi_ck3_bridge_v2_action_type').GetValue, '(CFixedPoint)16' ) ), And( GreaterThan_CFixedPoint( GetPlayer.MakeScope.Var('agi_ck3_bridge_event_option_request_present').GetValue, '(CFixedPoint)0' ), And( GreaterThan_CFixedPoint( GetPlayer.MakeScope.Var('agi_ck3_bridge_event_option_requested_event_id').GetValue, '(CFixedPoint)0' ), And( GreaterThan_CFixedPoint( GetPlayer.MakeScope.Var('agi_ck3_bridge_event_option_requested_option_code').GetValue, '(CFixedPoint)0' ), EqualTo_CFixedPoint( GetPlayer.MakeScope.Var('agi_ck3_bridge_event_option_requested_index').GetValue, IntToFixedPoint( Add_int32( PdxGuiWidget.GetIndexInDataModel, '(int32)1' ) ) ) ) ) ) ) ) )]\"",
    "\ton_start = \"[GetScriptedGui('agi_ck3_event_option_consume_gui').Execute( GuiScope.SetRoot( GetPlayer.MakeScope ).End )]\"",
    "\ton_start = \"[EventOption.Select]\"",
    "}",
)


def _indented_patch(indent: str) -> str:
    lines = []
    for line in PATCH_STATE_LINES:
        lines.append(indent + "\t" + line if line else "")
    return "\n".join(lines)


def patch_event_windows_gui(vanilla_text: str) -> str:
    if PATCH_SENTINEL in vanilla_text:
        raise ValueError("source event_windows.gui already contains AGI-CK3 event option bridge marker")
    patched_lines: list[str] = []
    inserted = 0
    for line in vanilla_text.splitlines():
        stripped = line.strip()
        if stripped == INSERT_TARGET:
            indent = line[: len(line) - len(line.lstrip())]
            patched_lines.append(f"{indent}button_eventoption = {{")
            patched_lines.append(_indented_patch(indent))
            patched_lines.append(f"{indent}}}")
            inserted += 1
        else:
            patched_lines.append(line)
    if inserted == 0:
        raise ValueError("could not find CK3 event option item insertion point")
    trailing_newline = "\n" if vanilla_text.endswith("\n") else ""
    return "\n".join(patched_lines) + trailing_newline


def generate_event_windows(game_gui_dir: Path, mod_gui_dir: Path) -> list[Path]:
    """Regenerate all event-window overrides (selector included) from the
    installed game. Run after every game update, before installing the
    poll-runner injections."""
    out_dir = mod_gui_dir / "event_windows"
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name in EVENT_WINDOW_NAMES:
        source = (game_gui_dir / "event_windows" / name)
        text = source.read_text(encoding="utf-8-sig", errors="replace")
        patched = patch_event_windows_gui(text)
        target = out_dir / name
        target.write_text(patched)
        written.append(target)
    return written
