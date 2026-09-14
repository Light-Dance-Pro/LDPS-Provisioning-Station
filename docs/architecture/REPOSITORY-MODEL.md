# Repository Authority and OS Integration Model

## Purpose

Keep a project repository independently understandable while Xavier's private deTrouble OS can
connect it to cross-project Knowledge and Planning. One changing proposition has one authority
owner; links replace copied truth.

## Ownership boundary

| Plane | Owns | Does not own |
|---|---|---|
| Repository authority | Code, README, current STATUS, durable docs, accepted ADRs, project Resources, tests, Git evidence and live-system state | Personal AI behavior, Source Episodes, lifecycle receipts, private Knowledge claims or OS Planning |
| OS-managed analysis and management | Context Knowledge, Source Episodes, lifecycle records, Portfolio models, OGSM, OKRs, Backlogs, Sprints and cross-project graph | Product truth, runtime state, collaborator procedures or authorization to change this repository |

The repository remains complete for collaborators and AI tools that do not have deTrouble OS.
The OS may read repository sources and express an accepted or observed result back into the
smallest suitable repository surface. It links to that owner instead of copying changing truth.

## Repository surfaces

- `README.md` is the tool-neutral entry and map.
- `STATUS.md` is the concise current projection, not a private Backlog or session log.
- `docs/strategy/` owns shared product purpose, direction and strategy models that collaborators
  need to interpret current work.
- `docs/architecture/` and `docs/reference/` own durable product meaning and lookup contracts.
- `docs/decisions/` owns accepted choices and their supersession chain.
- `docs/how-to/` and `docs/runbooks/` own repeatable contributor and operator procedures.
- `docs/archive/` owns dated, explicitly non-authoritative evidence.
- Project Resources or their stable locators stay with the repository whose work needs them.
- Commits and pull requests preserve change intent, rationale, evidence and integration context at
  the appropriate scope.

Repository docs may contain purpose, future direction and accepted design. They are not merely a
code index. They present collaborator-relevant results in the repository's own language and
structure; they do not reproduce private framework worksheets or lifecycle receipts.

## OS interaction

deTrouble OS may derive source-aware analytic Knowledge or private Planning from repository code,
docs, ADRs, Resources, sessions and real-world feedback. Those OS products remain outside this
repository even when their subject is this project.

When a private analysis changes shared project meaning, the accepted result is expressed here as
an update to code, STATUS, a durable document, ADR, runbook, dated evidence, issue, commit or pull
request. The OS record points to that expression. Neither record overrides the current owner
request or live repository authority.

Top-level `knowledge/` and `planning/` are not reserved product names, but the deTrouble-specific
record shapes formerly stored there do not belong in a generated project repository. The portable
repository check rejects those known OS artifact patterns without prohibiting a product that
legitimately implements a knowledge base or planning feature.

## Agent and contributor boundary

This Template contains no `AGENTS.md`, `CLAUDE.md`, Skills, Hooks, memory or secrets by default.
An owning repository may later add thin shared tool guidance by explicit project decision, but it
remains navigation and workflow guidance rather than personal memory or project authority.
Repository purpose, state, design and operation must remain recoverable without one model or one
person's local setup.

## Validation boundary

Shared validation lives in committed tools, regression fixtures and read-only CI. The base profile
covers documentation structure and links, local-file safety and known deTrouble OS artifact
leakage. It does not prove document truth, strategic quality, current runtime behavior or OS
Knowledge quality. Project-native lint, build and tests are added after the generated repository's
stack is known.
