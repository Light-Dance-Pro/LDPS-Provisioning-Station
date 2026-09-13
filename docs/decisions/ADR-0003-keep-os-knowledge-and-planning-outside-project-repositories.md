# ADR-0003: Keep OS Knowledge and Planning Outside Project Repositories

- **Status:** Accepted
- **Date:** 2026-09-13
- **Supersedes:** ADR-0001 section 2 and its repository-local Knowledge/Planning model

## Context

The former Template stored deTrouble Knowledge candidates and reviewed claims inside every project
repository and allowed project-local OGSM, OKRs and Backlogs. Real Studio and Website use showed
that this mixes Xavier's private analytic and management products with collaborator-facing project
authority. It also makes repositories depend on lifecycle formats, Skills and Hooks their other
contributors do not use.

The reviewed migration preserved 100 Source Episodes and closeout receipts in deTrouble OS,
classified 15 Studio Knowledge-shaped files as repository authority or historical evidence, and
verified that the two project repositories remained independently understandable through README,
STATUS, docs, code, tests and Git history.

## Decision

Generated project repositories contain one tool-neutral authority plane: code, README, STATUS,
durable docs, ADRs, project Resources, tests and delivery evidence. deTrouble Source Episodes,
Context Knowledge, lifecycle records and private Planning live in OS or an OS-managed repository.

OS may analyze repository sources and express an accepted or observed result back to its proper
repository surface. It links the private record to that expression; it does not copy private
framework instances, receipts or changing authority into both places.

Portable repository validation rejects known deTrouble-specific record patterns without reserving
generic product folder names such as `knowledge` or `planning`.

## Consequences

- New repositories do not require Xavier's OS, Codex setup or lifecycle formats.
- Collaborators retain project purpose, state, design, decisions, procedures and change evidence.
- Cross-project analysis and management can evolve without imposing private formats on product
  repositories.
- Existing repositories require source-led migration. This Template decision does not by itself
  authorize deletion from another repository.
