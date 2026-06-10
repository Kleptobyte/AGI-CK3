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
| `2026-06-10-claude-code` | claude-code (claude-fable-5) | survived_first_year, 5 ladder points; 14 steps, 2 agent_invalid; resolved the intro event via the recorded slot-1 gamble, then waited out the year |
| `2026-06-10-codex` | Codex (GPT-5) | survived_first_year, 5 ladder points; 11 steps, 0 failures; took gather-provisions (probe→take), resolved its event via a stable option, then waited out the year |

Both runs start from the same 1066.9.15 landless-adventurer campaign and
reach the same score by different paths — outcome parity with divergent
trajectories is exactly what the step log, rationales, and conduct
ledger exist to surface. The Codex run was a cold start: an agent that
had never seen this repository cloned it, completed setup from
`doctor`'s next steps, and played through `AGENTS.md` unaided.
