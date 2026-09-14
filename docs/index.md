# Provisioning Station Documentation Map

This is the tool-neutral entry for durable Station documentation. Current reality belongs in
[STATUS.md](../STATUS.md). Cross-product identity and provisioning decisions belong to
[LDPS-Hardware](https://github.com/Light-Dance-Pro/LDPS-Hardware/tree/main/docs/architecture/provisioning).

## Canonical buckets

| Bucket | Use |
|---|---|
| [strategy/](strategy/) | Shared product purpose and strategic direction |
| [architecture/](architecture/) | Station responsibilities, flows and system design |
| [decisions/](decisions/) | Repository-local decisions and supersession history |
| [reference/](reference/) | Durable lookup material and schemas |
| [how-to/](how-to/) | Goal-oriented contributor guides |
| [runbooks/](runbooks/) | Repeatable factory, recovery and operating procedures |
| [archive/](archive/) | Dated or superseded non-authoritative material |
| [_templates/](_templates/) | Starting shapes for durable document types |

Do not create aliases such as `adr/` or ad-hoc Markdown files at the top of `docs/`. Xavier's
private Knowledge lifecycle and Planning remain in deTrouble OS; this repository contains the
accepted or observed collaborator-facing product consequences.

## Current documents

- [Provisioning Station architecture](architecture/PROVISIONING-STATION.md) — roles, authority,
  flows and security boundaries.
- [Repository model](architecture/REPOSITORY-MODEL.md) — repository authority and the boundary
  around OS-managed Knowledge and Planning.
- [ADR-0001](decisions/ADR-0001-separate-repository-authority-knowledge-and-planning.md) —
  superseded history of repository-local Knowledge.
- [ADR-0002](decisions/ADR-0002-separate-shared-checks-from-personal-hooks.md) — shared checks and
  personal-tool boundary.
- [ADR-0003](decisions/ADR-0003-keep-os-knowledge-and-planning-outside-project-repositories.md) —
  current information-ownership decision.
- [Change communication](how-to/CHANGE-COMMUNICATION.md) — commit and pull-request evidence rules.

## Verification

```bash
python3 -m unittest tests.test_docs_lint tests.test_repo_lint tests.test_stage_targets
python3 tools/docs_lint.py
python3 tools/repo_lint.py
```

These checks establish repository structure, current local-link integrity and isolated stage-target
behavior. They do not establish live Cloud, factory-device or recovery-path behavior.
