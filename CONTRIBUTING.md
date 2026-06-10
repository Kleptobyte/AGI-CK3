# Contributing

AGI CK3 holds a narrow claim: agents act only through validated, legal
CK3 mechanics, and every claimed result is provable from artifacts.
Contributions are judged against that bar.

## Ground rules

- The registry (`src/ck3env/registry.py`) is the single source of truth
  for the action surface. New action families add one registry row and
  one mod dispatch branch; nothing else hardcodes family knowledge.
- Generated request scripts contain numeric variables and one entrypoint
  call only — never gameplay effects. Tests enforce this invariant.
- A family's lifecycle advances only with live certification evidence:
  truthful advertisement, probe both ways, guarded execution, idempotent
  redelivery, and precise blockers.
- Public docs describe the system, never development sessions. No
  personal paths, hostnames, credentials, saves, or Paradox content may
  enter the tree.

## Workflow

```bash
make test          # must stay green
python -m ck3env doctor
```

Keep changes small and tested. The offline suite runs without CK3; live
certification requires a local install and is documented in
`docs/architecture.md`.
