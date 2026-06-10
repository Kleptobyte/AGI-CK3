# Project Target

AGI CK3 exists to test whether agents can make legal, state-grounded,
long-horizon strategic decisions in Crusader Kings III through a narrow,
auditable adapter.

The target is:

> An agent gets only sanctioned observations, chooses only sanctioned legal
> actions, and every claimed result is proven by CK3 state, replayable
> artifacts, and a sealed scorer.

The repo is still a prototype. The target is not to make CK3 easy for agents,
and not to build a cheat interface. The target is to make each run honest enough
that another evaluator can inspect what the agent knew, what it chose, what CK3
allowed, what changed, and why the run continued or stopped.

## Claim Boundary

The defensible claim is narrow:

> AGI CK3 evaluates agents' ability to use a standardized observation,
> action, checkpoint, and scoring protocol to pursue long-horizon CK3 goals
> through legal game mechanics.

Do not claim that this proves general intelligence, matches human play, or has
completed the full landless-to-HRE challenge until the release gates below are
actually satisfied.

## Core Contract

The public loop stays small:

```text
observe -> act current_affordance_id -> verify checkpoint -> score/block
```

The harness owns:

- extraction and redaction;
- current legal affordance IDs;
- action validation and CK3 guard checks;
- runtime delivery receipts;
- checkpoint verification;
- scoring, blockers, and proof bundles.

The agent owns:

- strategy;
- memory and planning;
- choosing one current affordance ID;
- stopping or reporting insufficient observation when appropriate.

The harness must not suggest the best strategy, hide a direct shortcut inside a
legal-looking action, or turn unsupported CK3 mechanics into fake success.

## Non-Negotiables

- CK3 remains the source of game truth.
- Agents never get raw console authority, save edits, direct grants, or hidden
  task/scorer state.
- Public actions are affordance-first and valid only for the observation that
  produced them.
- Every official action family has a typed verifier.
- Event options are resolved deterministically or the run stops with an exact
  blocker.
- `wait_days` is blocked while a front player event is pending.
- A run without a proof bundle does not have an official score.
- Failures are labeled precisely as agent, CK3, runtime, scorer, or harness
  failures.
- Public docs distinguish proven behavior from intended behavior.

## Minimum Environment Shape

The CLI can keep the current verbs, but the formal environment contract should
map cleanly to:

```text
reset(task_id, seed, options) -> observation, info
observe() -> observation, info
legal_actions() -> action_set
step(action_id) -> observation, reward, terminated, truncated, info
verify(checkpoint) -> transition_proof
score() -> scorecard
bundle() -> proof_bundle
close()
```

The Python API should expose the same semantics without forcing researchers to
shell out for every turn.

## Observation Requirements

Agent-visible observations must be:

- canonical and hashable;
- schema-versioned;
- redacted to benchmark-sanctioned fields;
- bounded rather than raw save dumps;
- sufficient for reasonable play;
- non-strategic, with no hidden best-action hints;
- traceable to CK3 state or documented harness computation.

Referee-private state may exist for scoring and debugging, but it must not be
mounted into the evaluated agent's observation channel.

## Action Requirements

The normal public action request is just:

```json
{
  "observation_hash": "...",
  "action_id": "current.affordance.id"
}
```

Expanded action metadata can describe family, targets, guards, risk, public
costs, expected effect, and validity scope. That metadata is descriptive. The
harness still rechecks legality at execution time.

Each action family moves through this lifecycle:

```text
missing -> offline implemented -> probeable -> live-proven -> certified
```

Official tasks may use only live-proven or certified families.

## Proof Bundle

Every official run should produce a bundle with:

- benchmark version;
- CK3 version, checksum, DLC profile, and mod manifest;
- task ID, seed, and start manifest;
- agent manifest and permissions;
- observation/action transcript;
- action legality receipts;
- pre/post checkpoint hashes;
- transition records;
- scorecard and failure tags;
- runtime logs redacted for public sharing;
- reproduction command.

The scorer must be deterministic and recomputable from sealed CK3 state plus
sealed transition records. Agent-written text is never primary proof.

## Release Gates

Do not treat the project as a completed benchmark until these gates pass:

1. Claim hygiene: docs say exactly what is proven and what is not.
2. Conformance: one command validates schemas, sample run, audits, and install
   readiness.
3. Event option proof: front event options clear deterministically with live
   verification.
4. Action certification: every official task uses only live-proven or certified
   action families.
5. Task suites: conformance, micro, subsystem, medium, and full HRE task shapes
   have manifests, budgets, and success/failure predicates.
6. Sealed evaluation: the evaluated agent cannot tamper with saves, scorer,
   mod, harness, hidden manifests, or proof bundles.
7. Scoring: progress, success, cost, invalid-action rate, crash rate, and
   failure categories are computed from proof bundles.
8. Baselines: random, wait, heuristic, direct-policy, scaffolded-policy, and
   human baselines are defined or explicitly blocked.
9. Reproducibility: results are reported across seed suites with intervals and
   per-family breakdowns.
10. Review: limitations, threat model, and known gaps are public before broad
    claims are made.

## Roadmap

### Phase 1: Formal Contract

Deliver versioned schemas for observations, actions, transitions, tasks,
scores, and proof bundles. Add canonical serialization, observation hashes,
stale-action rejection, and a Python environment facade that matches the CLI
semantics.

### Phase 2: Event Options

Solve deterministic front player event option selection. Expose one affordance
per known front option, recheck the event fingerprint, execute through the
trusted path, checkpoint, and verify that the fingerprint cleared or changed.

### Phase 3: Action Certification

Create an action-family registry with lifecycle states, blockers, verifiers,
and live proof requirements. Prioritize wait, event option, camp movement,
contract acceptance, sway, gift, marriage, alliance, claim war, army movement,
peace, title creation/usurpation, vassalage/factions, decisions, and HRE
predicates.

### Phase 4: Task Suites

Define task manifests for conformance tasks, micro action-family tasks,
subsystem arcs, medium campaign tasks, and the full landless-to-HRE challenge.
Separate public smoke, public development, validation, and official held-out
sets.

### Phase 5: Sealed Runner

Separate the evaluated agent from saves, hidden manifests, scorer, mod, and raw
runtime controls. Mount benchmark internals read-only where possible and make
the controller/referee the only authority that can accept actions and write
proof artifacts.

### Phase 6: Scoring And Reporting

Make scorecards recomputable from proof bundles. Report success, normalized
progress, costs, invalid actions, unsupported blockers, crash/recovery events,
and failure taxonomy. Aggregate by task family and seed suite.

### Phase 7: Baselines And Review

Run random, wait, heuristic, LLM-policy, scaffolded-policy, and human baselines
where feasible. Publish limitations, threat model, and release notes before
calling for broader use.

## Work Tracking

GitHub is the source of truth for current issue IDs and status. Docs should
name durable work areas, not copy active issue lists that will drift.

Hub issues should exist for:

- contract and schemas;
- event option resolution;
- action-family certification;
- task suites and manifests;
- scoring and proof bundles;
- sealed runner and security model;
- baselines and human evaluation;
- live run proof;
- mid-run handoff;
- public readiness and claim hygiene;
- release governance and leaderboard rules.

Implementation issues should link back to the relevant hub issue in GitHub
unless the work is genuinely cross-cutting.
