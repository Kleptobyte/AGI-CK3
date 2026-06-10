"""ck3env — AGI-CK3 v3 environment core.

The registry is the single source of truth for the
action surface; the mod is the runtime authority on resolution and guards;
saves are periodic ground truth; debug.log telemetry is the per-step bus.
"""

__version__ = "3.0.0-dev"

PROTOCOL_VERSION = 1
# Bracket-free: [ ] is datatype syntax inside localization strings.
TELEMETRY_TAG = "agi3>"
REQUEST_FILENAME = "agi3_request.txt"
RUNNER_WIDGET_NAME = "agi3_runner"
