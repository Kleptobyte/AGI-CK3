# AGI-CK3 portable runtime — RECIPE ONLY, never an image containing game
# files (OSWorld pattern: the runner supplies their own Steam license).
# Five gates (U1-U5) decide viability; see RUNBOOK.md. Direct-binary launch
# without the Paradox launcher is already proven on macOS (2026-06-10).
# CK3's Linux build is x86_64-only; pin the platform (Apple Silicon
# emulates via Rosetta — fine for packaging gates, NOT for perf gates).
FROM --platform=linux/amd64 ubuntu:24.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl lib32gcc-s1 \
    xvfb x11-utils xdotool \
    mesa-vulkan-drivers vulkan-tools libvulkan1 \
    libsdl2-2.0-0 libgl1 fontconfig \
    python3 \
    && rm -rf /var/lib/apt/lists/*

# steamcmd (game download at runtime with the USER'S credentials; nothing
# is baked into the image)
RUN mkdir -p /opt/steamcmd && cd /opt/steamcmd \
    && curl -sSL https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz | tar zx

ENV CK3_DIR=/ck3 \
    CK3_USER_DIR=/ck3-user \
    DISPLAY=:99 \
    SDL_VIDEODRIVER=x11

WORKDIR /harness
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
