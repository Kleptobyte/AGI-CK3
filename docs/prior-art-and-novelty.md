# Prior Art And Novelty

AGI-CK3 is not novel because it uses a game for AI evaluation. That category is
well established.

Relevant adjacent work:

- CivBench evaluates LLM strategists in multiplayer Civilization V with
  progress-based measurements:
  <https://arxiv.org/abs/2604.07733>
- Voyager uses LLMs as an open-ended Minecraft agent with environment feedback
  and an executable skill library:
  <https://arxiv.org/abs/2305.16291>
- NetHack Learning Environment is a long-horizon, procedurally generated,
  stochastic game benchmark for RL agents:
  <https://arxiv.org/abs/2006.13760>
- GameBench evaluates strategic reasoning across multiple game environments:
  <https://arxiv.org/abs/2406.06613>
- BALROG evaluates agentic LLM and VLM reasoning on a suite of games:
  <https://balrogai.com/>
- AI-GameFriend advertises CK3 advisor-mode tooling, where AI reads saves and
  suggests moves, but that is not the same as an auditable CK3 eval harness:
  <https://getnextool.com/ai-gamefriend>
- Generic agent benchmarks evaluate tool use, web tasks, coding, simulated
  work, and multi-domain agency; they are important context but are not
  CK3-specific social-strategy simulators.

AGI-CK3's narrower claim is:

```text
An auditable Crusader Kings III benchmark harness where agents act only through
validated legal CK3 mechanics, with structured state extraction, checkpointed
traces, scenario readiness, scoring, and explicit blockers for unsupported game
mechanics.
```

AGI-CK3 is not:

- a CK3 cheat bot;
- a visual desktop/OCR game player;
- a full CK3 CLI;
- proof that an agent can already complete the full landless-to-HRE challenge.

The useful evaluation angle is CK3's social and dynastic complexity: claims,
inheritance, faith, culture, legitimacy, rank, vassal politics, elections,
marriage, schemes, wars, and long delayed consequences. The harness is valuable
only if it preserves those mechanics instead of replacing them with direct
state edits.
