# AGI CK3 Eval Harness Mod

This is the CK3-native side of the AGI-CK3 benchmark harness.

AGI CK3 is an independent prototype. It is not affiliated with, endorsed by, or
sponsored by Paradox Interactive. This repo does not include CK3 assets, saves,
credentials, launcher databases, or game files.

Current features:

- `AGI-CK3 Eval Probe` decision
- `AGI-CK3 Eval Status` decision
- `AGI-CK3 Refresh Telemetry` decision
- character variables:
  - `agi_ck3_eval_probe`
  - `agi_ck3_eval_probe_count`
  - `agi_ck3_eval_telemetry_version`
  - `agi_ck3_eval_player_faith`
  - `agi_ck3_eval_player_culture`
  - `agi_ck3_eval_player_is_christian`
  - `agi_ck3_eval_primary_title`
  - `agi_ck3_eval_primary_title_tier`
  - `agi_ck3_eval_highest_title_tier`
  - `agi_ck3_eval_realm_size`
  - `agi_ck3_eval_is_landed`
  - `agi_ck3_eval_is_landless_adventurer`
  - `agi_ck3_eval_hre_exists`
  - `agi_ck3_eval_player_controls_hre`
  - `agi_ck3_eval_hre_holder_is_christian`
  - `agi_ck3_eval_yearly_ticks`
- a yearly on_action marker after probe activation
- harmless confirmation events
- guarded V2 bridge dispatch for documented action types, including telemetry,
  bounded waiting, decisions, interactions, task contracts, camp relocation,
  marriage, education, lifestyle focus, and scoped war probes/actions

The mod is intentionally conservative. It does not grant titles, gold, claims,
faith conversion, culture conversion, spouses, alliances, armies, opinion, or
character deaths. Bridge actions must pass allowlisted CK3-style guards before
the mod executes anything.

Install from the repo root:

```bash
make install-mod
```

See the repo-level `LICENSE` for the project license. If you redistribute the
mod, make sure your distribution also complies with the applicable CK3 and
Paradox terms.
