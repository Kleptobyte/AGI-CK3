# Architecture

AGI-CK3 evaluates AI agents playing Crusader Kings III through legal,
game-guarded actions. Every run is replayable and re-scorable from
artifacts alone. This document describes the system; `docs/roadmap.md`
states the project target and release gates.

## Components

1. `src/ck3env/` — Python library and CLI: environment API, referee,
   scorer, proof bundles.
2. `mods/agi_ck3_eval/` — the CK3-native authority: publishes action
   candidates, re-checks the game's own availability guards, executes at
   most one legal effect per request, emits telemetry.
3. Benchmark protocol — versioned task manifests, seed suites, scoring,
   baselines, and per-family certification status.

## Transport

The mod injects small poll widgets into every GUI window class that can
hold the foreground (HUD, console, all event-window types). Each widget's
animation loop executes `run agi3_request.txt` from the game's run
directory roughly twice per second. The harness writes request files
atomically; the game consumes them.

Properties the protocol guarantees:

- **Consume-once.** Each request carries a monotonic `req_id`. The mod
  consumes a given id at most once; redelivery re-acknowledges without
  re-executing, so delivery retries are always safe.
- **Single non-idempotent actor.** The engine animates only the active
  GUI layer, so no widget may own work that cannot be safely refired.
  Console verbs that change state outside the request protocol
  (`tick_day`, `save`) are therefore executed only by the harness via
  verified keyboard injection after the mod acknowledges the request —
  one actor, no double-application, no dependence on which layer is live.
- **Completion semantics.** Staged work acknowledges on consumption and
  reports a terminal result only on completion (`tick_day` is
  asynchronous; the result carries the post-completion date).
- **Liveness.** A heartbeat line accompanies every poll. Silence is
  classified (runner never seen / request ignored / heartbeat stale /
  staged work stalled), never guessed. Note: the game process renames
  itself (`comm` becomes `Main Thread`); supervisors must track the
  launch PID, not the process name.

## Observation

- Fast path: the mod emits ASCII `key=value` telemetry lines, tagged and
  schema-versioned, into the game's debug log — heartbeat per poll, state
  facts and candidate slots on refresh, results per request, dates via
  engine date lines. The harness tails the log from a saved offset.
- Truth path: checkpoint saves at a configurable cadence and at
  milestones, used for verification and proof bundles — never as the
  per-step bus. Targeted save predicates stay in the standard library; an
  external parser sidecar may be used for full-fidelity research
  extraction.
- The observation is a single canonical JSON tree: every fact appears
  once, is traceable to telemetry or a checkpoint, and the document hash
  (`observation_id`) binds actions to the observation that produced them.

## Action surface

A single registry table defines every action family: verbs, parameter
schema, resolver kind, the CK3 guard the mod re-checks, verifier, and
certification lifecycle. Adding a family means one registry row plus one
mod dispatch branch.

Dynamic targets use mod-published candidate slots: on each refresh the
mod enumerates candidates from live game scopes under mechanical criteria
(never strategic curation) and the harness relays them. The harness never
predicts what the game will resolve.

Affordance IDs follow `family.verb#slot`. Paired families expose a probe
verb; the execute verb is advertised only after a successful probe for
the same slot, and a blocked re-probe revokes that grant. Slot
publication clears stale slots and grants on every refresh.

Event options: option selection is performed by the game's own UI layer.
Generated event-window overrides add a guarded auto-select state per
option button that fires only when the window is on top, the option is
valid and not flagged dangerous, and the armed request's index matches
the option's position. Unknown events stop gameplay actions honestly —
`wait` is blocked while a player event is pending, because the engine
halts time over a blocking event.

## Environment API

```python
class CK3Env:
    reset(task_id, seed) -> Observation
    observe() -> Observation
    legal_actions() -> list[Affordance]
    step(affordance_id, observation_id, rationale=None) -> StepResult
    score() -> Scorecard
    bundle() -> Path
```

The referee process runs the loop and owns the game's run directory,
saves, logs, scorer, and bundles. The evaluated agent is a policy:
observation in, one affordance id out. `step` rejects stale observation
ids. Lifecycle gates enforce claim hygiene at runtime: families that are
not live-certified cannot execute in live mode (probeable families may
probe only); the certification gauntlet runs with an explicit override.

## Scoring

Three independent axes, all recomputable from bundles offline:

1. **Milestone ladder** — progress-dense, derived from mod-published
   primitives (gold, prestige, title tier, landless flag, HRE held) plus
   episode dates. Landless titular titles never count as land.
2. **Indices** — continuous measures reported separately; unpublished
   values are `null`, never zero.
3. **Conduct ledger** — counts of value-laden acts (imprisonments,
   murders, oath-breaks, …) reported alongside the score, never folded
   into it.

Every scorecard carries a failure taxonomy that distinguishes agent
faults from transport, game, and harness faults.

## Reproducibility

- Release pinning: game version and depot manifests, DLC list, mod hash,
  harness version.
- Episodes: task id, seed, start-save hash; official results use seed
  suites with intervals.
- Proof bundles contain observations, actions, telemetry, checkpoint
  hashes, and the scorecard; `ck3env rescore` reproduces scores with no
  game installed and rejects tampered artifacts.

## Runtime requirements

CK3 runs headless-ready under a virtual display with software Vulkan
(Mesa/llvmpipe); no GPU, Steam client, or Paradox launcher is required at
runtime. Memory floor is 16 GB for the game process; budget four or more
cores. Game content is never redistributed: operators download it with
their own license (see `infra/linux/`).
