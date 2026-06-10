#!/usr/bin/env bash
# Zero-agent survival-year run on a macOS workstation. Reboot first if the
# game has had a long interactive session (window-server state decays).
# Usage: scripts/mac-year.sh [run_dir] [days]
set -euo pipefail
RUN="${1:-runs/year-$(date +%Y%m%d-%H%M)}"
DAYS="${2:-360}"
USER_DIR="$HOME/Documents/Paradox Interactive/Crusader Kings III"
GAME_DIR="$HOME/Library/Application Support/Steam/steamapps/common/Crusader Kings III/game"
BIN="${GAME_DIR%/game}/binaries/ck3.app/Contents/MacOS/ck3"
caffeinate -dis & CAFF=$!
trap 'kill $CAFF 2>/dev/null; kill $(cat /tmp/ck3.pid 2>/dev/null) 2>/dev/null' EXIT
nohup "$BIN" --continuelastsave -nakama -debug_mode -develop -gdpr-compliant >/tmp/ck3_boot.log 2>&1 &
echo $! > /tmp/ck3.pid
LOG="$USER_DIR/logs/debug.log"
echo "booting (heartbeat wait)..."
until tail -c 3000 "$LOG" 2>/dev/null | grep -q "kind=hb"; do
  kill -0 "$(cat /tmp/ck3.pid)" 2>/dev/null || { echo "boot died"; tail -3 /tmp/ck3_boot.log; exit 1; }
  sleep 10
done
PYTHONPATH=src python3 -m ck3env reset --run "$RUN" --task survival-year --seed "$RANDOM" \
  --live --ck3-user-dir "$USER_DIR" >/dev/null
PYTHONPATH=src python3 -m ck3env survival-run --run "$RUN" --days "$DAYS" \
  --live --allow-uncertified --ck3-user-dir "$USER_DIR" \
  --game-dir "$GAME_DIR" --checkpoint-save "$USER_DIR/save games/agi3_checkpoint.ck3"
PYTHONPATH=src python3 -m ck3env bundle --run "$RUN"
echo "bundle: $RUN/bundle.zip"
