# Submissions

Reference proof bundles from completed episodes — self-reported and
rescore-verifiable. Each directory is one run: a self-declared agent
identity plus the full recorded trajectory (actions, rationales,
telemetry, scorecard). Verify any of them without the game installed:

```bash
python -m ck3env rescore submissions/<run>/bundle.zip
```

`rescore` recomputes the scorecard from the bundle's artifacts alone and
rejects tampering; the output includes the submission identity and stop
reason. See [AGENTS.md](../AGENTS.md) for how to produce one with your
own agent.

| run | agent | result |
| --- | --- | --- |
| `2026-06-10-claude-code` | claude-code (claude-fable-5) | survived_first_year, 5 ladder points; 14 steps, 2 agent_invalid; landless adventurer, 1066.9.15 → 1067.9.17 |
