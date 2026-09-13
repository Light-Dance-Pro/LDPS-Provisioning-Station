# ADR-0001: Separate Repository Authority, Knowledge and Planning

- **Status:** Accepted
- **Date:** 2026-08-31

## Context

The first Template coupled the documentation convention to Claude Code through a repository-local
`CLAUDE.md`. deTrouble OS later added federated `knowledge/` stores and, for some repositories,
OGSM, OKRs and Backlog under `planning/`. Applying those additions without an explicit ownership
model made repositories look inconsistent and could duplicate STATUS, ADRs, plans and Knowledge.
Other contributors do not share Xavier's Codex Skills, Hooks, OS checkout or automatic lifecycle.

## Decision

Use three non-overlapping layers:

1. Code, README, STATUS, durable docs, accepted ADRs and live evidence remain shared project
   authority.
2. Every repository generated from this Template is ready to own sourced `knowledge/` records, but
   the records remain analytic data and deTrouble OS owns Xavier's automation. Contributors update
   the authoritative project sources through their normal workflow and need not maintain Knowledge
   manually.
3. `planning/` is absent by default and is added only after an explicit decision that the repository
   owns a planning scope. STATUS summarizes current reality and links to Planning instead of copying
   its intended work.

The Template contains no model-specific agent entry, Skill, Hook, memory or Git hook by default. A
repository may later add a thin shared tool-guidance entry by explicit project decision, but it is
not project authority. Deterministic layout and link checks use one tested Python tool in read-only
CI.

## Consequences

- A generated repository remains understandable and maintainable without Xavier's local AI setup.
- Knowledge can be created consistently across Xavier's projects without becoming another project
  authority or a task store.
- Ordinary component repositories are not forced to carry OGSM, OKRs or Backlog they do not own.
- Existing repositories require a source-led migration; this decision does not authorize a bulk
  rename, file move or deletion across the estate.
