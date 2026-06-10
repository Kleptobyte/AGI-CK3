"""In-game auto-runner transport (see docs/architecture.md).

A GUI widget injected under
hud.gui's `meta_info` fires `run agi3_request.txt` at ~2 Hz, focused or not,
p50 write-to-observed-result 212 ms. Run files are re-read fresh on every
invocation.

Delivery contract: write the request file atomically; the runner executes it
on its next tick; the mod consumes a req_id at most once and (re-)emits a
result line for it. Redelivery is therefore always safe — on timeout we
rewrite the same file and keep waiting, and we classify failures from
heartbeat staleness, never by guessing.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import REQUEST_FILENAME, RUNNER_WIDGET_NAME
from .observe import LogTail, Snapshot, TelemetryEvent

RUNNER_SENTINEL = "### agi3 runner v1 (generated; do not edit by hand)"
RUNNER_ANCHOR = '\tname = "meta_info"\n\tvisible = "[IsDefaultGUIMode]"\n'

# Both state durations in seconds; ~2 fires/sec total, measured 1.9 Hz live.
RUNNER_POLL_SECONDS = 0.5

PULSE_REQUEST = "# agi3 at-rest pulse: telemetry only, no gameplay effects\nagi3_pulse = yes\n"


class TransportError(RuntimeError):
    pass


@dataclass(frozen=True)
class Receipt:
    status: str  # "acked" | "rejected" | "timeout"
    req_id: int
    latency_ms: float | None
    attempts: int
    result: dict[str, str] | None
    failure_class: str | None = None


def generate_runner_gui(vanilla_hud_text: str) -> str:
    """Inject the auto-runner widget into a copy of the installed hud.gui.

    Engine requirement: animation states MUST carry
    `trigger_on_create = yes` and at least one animated property (alpha),
    or they load silently and never run.
    """
    if RUNNER_ANCHOR not in vanilla_hud_text:
        raise TransportError(
            "hud.gui anchor not found; CK3 layout changed — regenerate "
            "support for this game version before installing the runner"
        )
    # Forced visible: event windows switch the GUI mode off-default, which
    # would hide the host and freeze its animation clock. The runner must
    # tick in every GUI mode.
    widget = (
        '\tname = "meta_info"\n\tvisible = yes\n'
        + f"\t{RUNNER_SENTINEL}\n"
        + host_block("agi3_hud", extra_command="run agi3_event_clear.txt")
        + "\n"
    )
    return vanilla_hud_text.replace(RUNNER_ANCHOR, widget, 1)






def host_block(prefix: str, stagger: float = 0.0, extra_command: str | None = None) -> str:
    """Poll-only widget set for one GUI host layer. Staged console verbs
    (tick/save) run EXCLUSIVELY through Python keystroke kicks: Python is
    the single non-idempotent actor, so double-application is structurally
    impossible: the game animates only its active GUI layer, so no layer may own work that cannot be safely refired.

    extra_command chains a layer-identity marker (event open/clear): only
    the animating layer speaks, so presence is read from WHO is polling."""
    del stagger
    return _poll_widget(f"{prefix}_poll", extra_command)


def generate_console_gui(vanilla_console_text: str) -> str:
    """The console window is the SINGLE authority host for conditional
    (save/tick) widgets: it renders above every GUI mode, so staged work
    cannot stall behind modal events  — and
    keeping conditionals in exactly one host prevents double-firing
    `tick_day` from overlapping live layers. Poll runners stay redundant
    across layers (consume-once makes that harmless); conditionals do not.
    Live runs keep the console open; the heartbeat is the liveness check.
    """
    anchor = vanilla_console_text.find("{")
    if anchor < 0:
        raise TransportError("console.gui has no root block")
    insert_at = vanilla_console_text.find("\n", anchor) + 1
    block = f"\t{RUNNER_SENTINEL}\n" + host_block("agi3_console", stagger=0.55) + "\n"
    return vanilla_console_text[:insert_at] + block + vanilla_console_text[insert_at:]


def _poll_widget(name: str, extra_command: str | None = None) -> str:
    if extra_command:
        fire = f"[ExecuteConsoleCommandsForced('run {REQUEST_FILENAME};{extra_command}')]"
    else:
        fire = f"[ExecuteConsoleCommand('run {REQUEST_FILENAME}')]"
    return f"""\twidget = {{
\t\tname = "{name}"
\t\tsize = {{ 2 2 }}
\t\tstate = {{
\t\t\tname = _show
\t\t\ttrigger_on_create = yes
\t\t\tduration = {RUNNER_POLL_SECONDS}
\t\t\talpha = 0.9
\t\t\ton_finish = "{fire}"
\t\t\tnext = agi3_tick
\t\t}}
\t\tstate = {{
\t\t\tname = agi3_tick
\t\t\tduration = {RUNNER_POLL_SECONDS}
\t\t\talpha = 1
\t\t\ton_finish = "{fire}"
\t\t\tnext = _show
\t\t}}
\t}}"""




def install_runner(game_gui_dir: Path, mod_gui_dir: Path) -> Path:
    source = (game_gui_dir / "hud.gui").read_text(encoding="utf-8-sig")
    generated = generate_runner_gui(source)
    target = mod_gui_dir / "hud.gui"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"\xef\xbb\xbf" + generated.encode("utf-8"))
    return target


def runner_installed(mod_gui_dir: Path) -> bool:
    target = mod_gui_dir / "hud.gui"
    return target.exists() and RUNNER_SENTINEL in target.read_text(
        encoding="utf-8-sig", errors="replace"
    )


def write_request_atomic(ck3_run_dir: Path, text: str) -> Path:
    """Temp-file + rename so the runner never reads a partial request."""
    ck3_run_dir.mkdir(parents=True, exist_ok=True)
    final = ck3_run_dir / REQUEST_FILENAME
    temporary = ck3_run_dir / (REQUEST_FILENAME + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, final)
    return final


def restore_pulse(ck3_run_dir: Path) -> None:
    write_request_atomic(ck3_run_dir, PULSE_REQUEST)


class TransportState:
    """Monotonic req_id + log offset, durable across harness restarts."""

    def __init__(self, path: Path) -> None:
        self.path = path
        data = json.loads(path.read_text()) if path.exists() else {}
        self.last_req_id = int(data.get("last_req_id", 0))
        self.log_offset = int(data.get("log_offset", 0))

    def next_req_id(self) -> int:
        self.last_req_id += 1
        self.save()
        return self.last_req_id

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {"last_req_id": self.last_req_id, "log_offset": self.log_offset},
                indent=2,
            )
            + "\n"
        )


def _verified_keystroke(commands: list[str], ck3_pid: int, log_path: Path) -> bool:
    """Parity-safe console typing: the backtick toggle state is unknowable,
    so verify via the console's own log line and retry once with a leading
    toggle (verified retry). Wrong-parity spill risk is bounded to a
    single attempt."""
    offset = log_path.stat().st_size if log_path.exists() else 0
    if _keystroke_kick(commands, ck3_pid) and _commands_logged(commands, log_path, offset):
        return True
    offset = log_path.stat().st_size if log_path.exists() else 0
    return _keystroke_kick(commands, ck3_pid, extra_toggle=True) and _commands_logged(
        commands, log_path, offset
    )


def _commands_logged(commands: list[str], log_path: Path, offset: int) -> bool:
    import time as _time

    deadline = _time.monotonic() + 4.0
    while _time.monotonic() < deadline:
        try:
            with log_path.open("rb") as handle:
                handle.seek(offset)
                chunk = handle.read().decode("utf-8", "replace")
        except OSError:
            return False
        if all(f"Running console command: {c}" in chunk for c in commands):
            return True
        _time.sleep(0.15)
    return False


def _keystroke_kick(commands: list[str], ck3_pid: int, extra_toggle: bool = False) -> bool:
    """F1 assured-liveness path: type console commands directly. CK3 freezes
    background GUI layers on top-layer changes, and window
    classes are open-ended — so GUI polling is the fast path, never the
    liveness guarantee. Keystrokes pierce every mode; everything they run is
    idempotent (consume-once requests, claim files, after files)."""
    import subprocess

    lines = [
        'tell application "System Events"',
        f"set frontmost of first process whose unix id is {ck3_pid} to true",
        "delay 0.6",
    ]
    if extra_toggle:
        lines += ["key code 50", "delay 0.4"]
    lines += ["key code 50", "delay 0.4"]
    # Clear any residue in the console input line (wrong-parity spills
    # concatenate garbage and poison every subsequent command).
    lines += ["repeat 60 times", "key code 51", "end repeat", "delay 0.2"]
    for command in commands:
        lines += [f'keystroke "{command}"', "key code 36", "delay 0.4"]
    lines += ["key code 50", "end tell"]
    try:
        proc = subprocess.run(
            ["osascript", "-e", "\n".join(lines)],
            capture_output=True, timeout=20,
        )
        return proc.returncode == 0
    except Exception:
        return False


def _ck3_pid() -> int | None:
    import subprocess

    try:
        out = subprocess.run(["pgrep", "-x", "ck3"], capture_output=True, text=True, timeout=5)
        pids = [int(x) for x in out.stdout.split()]
        return pids[0] if len(pids) == 1 else None
    except Exception:
        return None


class AutoRunnerTransport:
    """Hybrid transport: in-game GUI runners are the fast path (~200 ms);
    keystroke kicks guarantee liveness when no GUI layer is animating."""

    def __init__(
        self,
        ck3_run_dir: Path,
        log_path: Path,
        state: TransportState,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.ck3_run_dir = ck3_run_dir
        self.tail = LogTail(log_path, state.log_offset)
        self.state = state
        self.clock = clock
        self.sleep = sleep

    def drain(self, snapshot: Snapshot) -> list[TelemetryEvent]:
        events = self.tail.read_new()
        for event in events:
            snapshot.apply(event)
        # The mod's consume-once counter is authoritative: a fresh run dir
        # must not reuse req_ids the mod already consumed (they would re-ACK
        # as stale forever). The heartbeat broadcasts req_last; sync up.
        if (
            snapshot.last_consumed_req is not None
            and snapshot.last_consumed_req > self.state.last_req_id
        ):
            self.state.last_req_id = snapshot.last_consumed_req
        self.state.log_offset = self.tail.offset
        self.state.save()
        return events

    def deliver(
        self,
        request_text: str,
        req_id: int,
        snapshot: Snapshot,
        timeout_seconds: float = 10.0,
        redeliver_after_seconds: float = 3.0,
        poll_seconds: float = 0.02,
        staged_plan: tuple[str, float, str] | None = None,
        kick_after_seconds: float = 6.0,
    ) -> Receipt:
        """staged_plan = (work_command, settle_seconds, after_command) for
        families whose work is a console verb. On ack, Python executes the
        plan via keystrokes — the only path allowed to run non-idempotent
        commands."""
        started = self.clock()
        start_hb = snapshot.last_heartbeat_seq
        ack_seen = False
        kicks = 0
        write_request_atomic(self.ck3_run_dir, request_text)
        attempts = 1
        next_redeliver = started + redeliver_after_seconds
        next_kick = started + kick_after_seconds
        while self.clock() - started < timeout_seconds:
            for event in self.drain(snapshot):
                if event.kind == "ack" and event.get_int("req") == req_id:
                    ack_seen = True
                    next_redeliver = float("inf")
                    if staged_plan is not None:
                        work, settle, after = staged_plan
                        pid = _ck3_pid()
                        if pid is not None:
                            _verified_keystroke([work], pid, self.tail.log_path)
                            deadline = self.clock() + settle
                            while self.clock() < deadline:
                                self.sleep(poll_seconds)
                                self.drain(snapshot)
                            _verified_keystroke([after], pid, self.tail.log_path)
                        staged_plan = None  # exactly once
                    continue
                if event.kind in {"result", "reject"} and event.get_int("req") == req_id:
                    restore_pulse(self.ck3_run_dir)
                    status = "acked" if event.kind == "result" else "rejected"
                    return Receipt(
                        status=status,
                        req_id=req_id,
                        latency_ms=(self.clock() - started) * 1000,
                        attempts=attempts,
                        result=dict(event.fields),
                    )
            now = self.clock()
            if now >= next_redeliver:
                write_request_atomic(self.ck3_run_dir, request_text)  # safe: consume-once
                attempts += 1
                next_redeliver = now + redeliver_after_seconds
            if now >= next_kick and kicks < 6:
                # Liveness kicks are idempotent-only: re-run the request
                # (consume-once) or re-run the after file (safe re-result).
                pid = _ck3_pid()
                if pid is not None:
                    if not ack_seen:
                        _verified_keystroke([f"run {REQUEST_FILENAME}"], pid, self.tail.log_path)
                    elif staged_plan is None and "after" in dir():
                        pass  # staged path already completed its kicks
                    kicks += 1
                next_kick = now + max(kick_after_seconds, 10.0)
            self.sleep(poll_seconds)
        restore_pulse(self.ck3_run_dir)
        if ack_seen:
            # Mod consumed it; the staged work never completed — e.g. no
            # GUI layer was animating to advance the settle window.
            failure_class = "staged_work_stalled"
        elif (
            start_hb is not None
            and snapshot.last_heartbeat_seq is not None
            and snapshot.last_heartbeat_seq > start_hb
        ):
            failure_class = "request_ignored"  # runner alive, consume never ran
        else:
            failure_class = self.classify_silence(snapshot)
        return Receipt(
            status="timeout",
            req_id=req_id,
            latency_ms=None,
            attempts=attempts,
            result=None,
            failure_class=failure_class,
        )

    def classify_silence(self, snapshot: Snapshot) -> str:
        """Distinguish dead transport from dead game using the heartbeat."""
        before = snapshot.last_heartbeat_seq
        self.drain(snapshot)
        if snapshot.last_heartbeat_seq is None:
            return "runner_never_seen"  # runner not installed / mod inactive
        if before is not None and snapshot.last_heartbeat_seq > before:
            return "request_ignored"  # runner alive, request not consumed: mod bug
        return "heartbeat_stale"  # game hung, crashed, or render loop stopped
