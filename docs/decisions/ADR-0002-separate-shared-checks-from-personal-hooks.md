# ADR-0002: Separate Shared Checks from Personal Hooks

- **Status:** Accepted
- **Date:** 2026-08-31

## Context

The predecessor Template described push/PR CI as an unskippable gate and Xavier's global Git
configuration still pointed to a Claude Code backup hook. In reality, a workflow is a quality
check rather than a merge gate unless repository rules require it. Contributor-local hooks also
cannot establish a shared contract because other contributors and automation do not inherit them.

Knowledge and Planning have different maturity and activation boundaries. Enforcing their full
semantic contracts in every generated repository would freeze evolving OS behavior and require
contributors to reproduce Xavier's personal environment.

## Decision

The required shared baseline consists of deterministic, tool-neutral checks committed with the
repository:

1. documentation layout, local links and anchors;
2. regression fixtures for accepted and rejected cases; and
3. rejection of tracked local environment files and macOS metadata while allowing explicit
   example environment files.

Read-only GitHub CI runs these checks on push and pull request. It is described as a check and
becomes a merge gate only when the generated repository's GitHub rules require its status.

The Template installs no Git hook. Xavier may use a personal Git safety hook, but it must not be a
dependency of the repository or contain model-specific documentation policy. Project-native code
lint, build and tests are added after the generated repository selects its stack. Knowledge
semantic validation and Planning traceability validation are opt-in profiles added only after the
owning contracts are stable and explicitly activated.

## Consequences

- Every contributor and CI runner can execute the same portable baseline.
- A red workflow cannot be mistaken for a platform-enforced merge block.
- Local `.env` files remain usable but cannot be committed without an explicit override.
- Knowledge and Planning quality cannot yet be inferred from the base check; their later profiles
  must state their activation and evidence boundaries.
