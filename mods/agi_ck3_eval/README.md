# AGI CK3 Eval Harness Mod

The CK3-native side of the AGI-CK3 benchmark harness: a guarded bridge
that lets the Python referee request actions and read telemetry while
the game's own rules keep final authority.

What it does:

- Consumes numbered request files (`run/agi3_request.txt`) exactly once
  via monotonic request ids; re-delivery is idempotent.
- Re-checks CK3's own availability guards before executing any action;
  a request that fails its guard is reported `blocked`, never forced.
- Publishes ASCII `agi3>` telemetry to `debug.log`: heartbeat, world
  state (gold, prestige, tier, landless, HRE), action results, conduct
  markers, event-window presence, and action slots.
- Publishes action slots by mechanical criteria only (e.g. courtiers for
  gifts, fixed title-holders for camp moves) — the mod never curates
  strategically; hinting would contaminate the benchmark.

The mod is intentionally conservative. It grants no titles, gold,
claims, conversions, spouses, alliances, armies, opinion, or deaths.
The evaluated agent never receives console authority: what the game's
rules forbid, the agent cannot do.

Install — register this directory with the game (no copying), then
generate the per-game-version GUI overrides:

```bash
python -m ck3env install-mod --ck3-user-dir "<CK3 documents dir>"
python -m ck3env doctor --ck3-user-dir "<CK3 documents dir>"   # prints the remaining steps
```

Enable "AGI CK3 Eval Harness" in a Paradox launcher playset and launch
with `-debug_mode -develop`.

AGI CK3 is an independent project, not affiliated with or endorsed by
Paradox Interactive. This repository contains no CK3 assets, saves,
credentials, or game files. See the repo-level `LICENSE`; redistribution
must also comply with applicable CK3 and Paradox terms.
