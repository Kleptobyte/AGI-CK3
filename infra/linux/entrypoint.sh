#!/usr/bin/env bash
# Gates U1-U5 in order; each prints PASS/FAIL with evidence.
set -uo pipefail
MODE="${1:-gates}"

echo "== U1: software Vulkan present =="
Xvfb :99 -screen 0 1280x800x24 &
sleep 2
vulkaninfo --summary 2>&1 | grep -E "GPU|llvmpipe|driverName" | head -5 || echo "U1 FAIL: no vulkan device"

if [ "$MODE" = "download" ]; then
  echo "== downloading CK3 with YOUR Steam login (never stored) =="
  /opt/steamcmd/steamcmd.sh +force_install_dir "$CK3_DIR" \
    +login "$STEAM_USER" +app_update 1158310 validate +quit
fi

if [ -x "$CK3_DIR/binaries/ck3" ]; then
  echo "== U2/U3: direct-binary boot under Xvfb+lavapipe =="
  mkdir -p "$CK3_USER_DIR"
  "$CK3_DIR/binaries/ck3" --continuelastsave -nakama -debug_mode -develop -gdpr-compliant &
  CK3_PID=$!
  for i in $(seq 1 60); do
    sleep 5
    if ! kill -0 "$CK3_PID" 2>/dev/null; then echo "U2 FAIL: ck3 exited early"; break; fi
    if grep -q "kind=hb" "$CK3_USER_DIR"/logs/debug.log 2>/dev/null; then
      echo "U2+U5 PASS: heartbeat under Xvfb"; break
    fi
  done
  ps -o %cpu,%mem -p "$CK3_PID" 2>/dev/null && echo "(U3 resource snapshot above)"
  echo "== U4: XTEST input injection =="
  xdotool key grave type "help" && xdotool key Return && echo "U4 sent (verify via debug.log console line)"
else
  echo "ck3 binary not present; run with MODE=download and STEAM_USER set"
fi
exec sleep infinity
