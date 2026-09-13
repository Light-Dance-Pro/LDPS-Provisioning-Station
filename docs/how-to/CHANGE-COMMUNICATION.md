# Communicate Repository Changes

## Outcome

Make each material change understandable to a collaborator or AI tool from Git and repository
sources alone. Commit and pull-request records complement README, STATUS, durable docs and ADRs;
they do not copy private deTrouble OS Knowledge, Planning or conversation history.

## Commit guidance

Write a result-oriented subject that names what the changeset accomplishes. Do not require a
Conventional Commits prefix unless this repository separately adopts one for release automation.

A subject alone is enough for a genuinely mechanical change whose purpose and effect are obvious.
Add a body when the commit contains a defect repair, observable product or design change,
migration, data/security/deployment effect, cross-repository consequence, or non-obvious research
or documentation result.

The body must make the relevant meaning recoverable, but it does not need fixed headings. Cover:

- the observed problem, owner intent or reason for the change;
- the established cause or governing rationale when one exists;
- what behavior, data, documentation or structure changed;
- the verification actually performed; and
- an important limitation, excluded scope or remaining risk when material.

Do not write `verified`, `fixed`, `working` or `deployed` beyond the evidence produced. Link a
durable document when the rationale is too large for the commit. Keep raw private dialogue,
credentials, complete lifecycle receipts and speculative reasoning out of Git messages.

### Examples

Mechanical change:

```text
Refresh generated device catalog
```

Defect repair:

```text
Reject stale node state during reconnect

The reconnect path accepted a cached revision after the server had advanced.
Compare the received revision before restoring state and return a visible stale-state result.

Verified with the reconnect regression and the repository test suite. This does not validate the
physical radio path.
```

Design or migration change:

```text
Move private planning records to deTrouble OS

Project collaborators need one tool-neutral repository authority plane, while private management
planning belongs to the OS-managed plane. Remove the legacy planning records and update README,
STATUS and docs to preserve the shared product meaning.

Validated with repository layout, link and applied-tree checks. Remote deployment is not included.
```

## Pull-request guidance

A pull request explains the integration outcome across its commits. State:

- the outcome and its source intent or accepted decision;
- included changes and material excluded scope;
- user, data, operational and cross-repository risks;
- matching tests, builds, runtime checks or other evidence;
- the documentation disposition (`none`, `local` or `cross-repo`) and why; and
- whether merge or push deploys, migrates data, changes schema, flashes hardware or has another
  consequential external effect.

Do not turn an assistant proposal, generated ADR, test or previous commit into evidence of owner
acceptance. If current instructions conflict with an older design, surface the conflict for owner
judgement instead of silently implementing the older source.

## Before committing

1. Confirm the staged diff is one coherent outcome and contains no unrelated work.
2. Run the evidence appropriate to the claim; do not substitute a lint pass for product behavior.
3. Reconcile changed shared meaning with README, STATUS, docs and decisions.
4. Check branch, push and deployment effects before publishing.

## Branch and worktree discipline

Treat the normalized remote repository as the project integration unit. A clone or worktree is an
execution surface, not another project and not a reason to create another branch.

- Keep one to three branches in active operation for a project, normally `main` or `master`, an
  optional `uat`, and one established working branch for the current owner outcome.
- Reuse the established working branch after aligning it with the latest integration branch. Do not
  create a branch per session, agent or worktree.
- Use another working branch only for a genuinely independent or blocked outcome. Do not combine
  unrelated work merely to remain under the branch cap.
- Use a detached worktree at an exact commit for paused, historical or read-only verification when
  no branch needs to move.
- After integration, retire the completed working branch and realign the established branch before
  reusing it. A squash merge does not make the old working branch current automatically.
- Before publishing a repository-wide contract or documentation migration, confirm that only one
  branch carries that shared patch.

These limits govern branches in active operation. They do not authorize deleting remote history,
open pull-request branches or collaborator work without evidence and owner review.
