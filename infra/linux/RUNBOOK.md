# Linux Runtime Recipe

Portable headless runtime for the harness. Game content is never baked
into images: operators download CK3 with their own Steam license at
provision time (DepotDownloader; note that classic steamcmd is a 32-bit
binary and will not run on VM classes without ia32 support).

## Acceptance gates

| Gate | Check | Pass signal |
| --- | --- | --- |
| U1 | software Vulkan present under Xvfb | `vulkaninfo` lists an llvmpipe device |
| U2 | game boots without Steam client or Paradox launcher | direct binary launch reaches asset loading; DLC store-backend errors are non-fatal |
| U3 | resources | 16 GB RAM floor for the game process; 4+ cores advised; 2-core/8 GB boxes OOM during boot even with swap |
| U4 | input injection | xdotool console keystrokes appear as executed commands in `debug.log` |
| U5 | harness stack | mod heartbeat lines flow; one request round-trips |

## Host preparation (Ubuntu 24.04)

```bash
apt-get install -y xvfb x11-utils xdotool vulkan-tools mesa-vulkan-drivers \
    libvulkan1 libsdl2-2.0-0 libgl1 libglu1-mesa libatomic1 fontconfig \
    python3 git curl
# game download (operator credentials; interactive Steam Guard):
DepotDownloader -app 1158310 -username <user> -dir /ck3 -os linux
chmod +x /ck3/binaries/ck3
```

User-dir plumbing: place the repo mod plus a descriptor under
`~/.local/share/Paradox Interactive/Crusader Kings III/mod/`, enable it in
`dlc_load.json`, and stage a campaign save. Launch:

```bash
Xvfb :99 -screen 0 1280x800x24 &
DISPLAY=:99 SDL_AUDIODRIVER=dummy /ck3/binaries/ck3 \
    --continuelastsave -nakama -debug_mode -develop -gdpr-compliant
```

Supervisor notes: track the launch PID, not the process name (the game
renames its comm to "Main Thread"); keep the display from sleeping; treat
kill-and-relaunch from the latest checkpoint as the standard recovery.

The Dockerfile in this directory packages the same gates; CK3 is
x86_64-only, so Apple Silicon hosts emulate and are suitable for
packaging checks, not performance gates.
