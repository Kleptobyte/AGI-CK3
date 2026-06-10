# AGI CK3

![AGI CK3 banner](docs/assets/agi-ck3-banner.png)

An evaluation harness for AI agents playing Crusader Kings III through
legal, game-guarded actions.

Agents receive structured JSON observations and choose one affordance ID
per step. A game-side mod re-checks CK3's own availability rules before
executing anything; the harness verifies results from telemetry and
checkpoint saves; every run produces a proof bundle that can be re-scored
without the game installed. The long-term benchmark goal:

> Start as a landless adventurer and legally work toward control or
> restoration of the Holy Roman Empire through normal CK3 mechanics.

The harness never grants titles, gold, claims, or other shortcuts, and an
evaluated agent never receives raw console authority. What the game's
rules forbid, the agent cannot do; what they allow, the agent must find.

## Status

Action families certify individually against the live game before they
may execute in evaluated runs:

| Family | Status |
| --- | --- |
| telemetry refresh, checkpoint, wait, decisions, camp movement | live-proven |
| gifts | probe-proven; execution pending a qualifying state |
| event options (catalog-safe) | selection path proven; catalog coverage growing |
| wars, marriage, education, alliances, contracts, lifestyle | implemented, awaiting live certification |

A 100-step unattended baseline run completes with zero human
interventions at ~310 ms median step latency. Linux/headless operation
(virtual display, software Vulkan, no Steam client or launcher) is
verified through game boot; see `infra/linux/` for the portable runtime
recipe and its acceptance gates.

## Quick start

Requirements: Python 3.11+, and CK3 via Steam for live runs.

```bash
git clone https://github.com/Kleptobyte/AGI-CK3.git
cd AGI-CK3
make test                      # offline suite, no game required
python -m ck3env doctor        # environment diagnosis
```

Live runs (macOS or Linux desktop today; see `infra/linux/` for servers):

1. Install the mod and generate the per-version GUI overrides:
   `python -m ck3env install-event-gui ...` and `install-runner ...`
   (paths printed by `doctor`).
2. Launch CK3 with `-debug_mode -develop`, the eval mod enabled, and a
   campaign loaded and paused.
3. Drive an episode:

```bash
python -m ck3env reset --run runs/demo --task smoke --seed 1 --live --ck3-user-dir "<CK3 documents dir>"
python -m ck3env observe --run runs/demo --live --ck3-user-dir "<CK3 documents dir>"
python -m ck3env step  --run runs/demo --live --ck3-user-dir "<CK3 documents dir>" <affordance_id> <observation_id>
python -m ck3env bundle --run runs/demo && python -m ck3env rescore runs/demo/bundle.zip
```

`baseline-run` drives the scripted baseline policy for unattended soak
runs. The Makefile is developer convenience only; the CLI and library are
the interface.

## Documentation

- [Architecture](docs/architecture.md) — transport, observation, action
  surface, scoring, reproducibility.
- [Roadmap](docs/roadmap.md) — project target and release gates.
- [Prior art](docs/prior-art-and-novelty.md) — where this sits among game
  benchmarks.
- [Linux runtime](infra/linux/RUNBOOK.md) — portable headless recipe.

## Not included

CK3 itself, saves, logs, credentials, or any Paradox-owned content.
Operators download the game with their own license; proof bundles let
third parties audit and re-score runs without owning it.

## License and affiliation

MIT (see [LICENSE](LICENSE)). AGI CK3 is an independent project, not
affiliated with or endorsed by Paradox Interactive. Crusader Kings III
belongs to Paradox Interactive.
