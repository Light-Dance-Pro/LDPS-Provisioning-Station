# Status — LDPS Provisioning Station

## Current reality

The `main` branch contains the factory Station application for LED Node and Control Hub
provisioning. It uses explicit Local, UAT and Production Cloud targets and rejects request-supplied
remote endpoint overrides. The repository does not deploy automatically.

The implemented operator surface contains automated Node and Hub flows. Node identity is written
over USB and committed to Cloud; Control Hub identity is written through its direct-local
provisioning channel and committed after restart/QC. Console Hub RF-bridge firmware is sent through
the assembled Control Hub. The factory Test Board supplies RF QC for LED Nodes.

## Verification boundary

- Repository structure, links and stage-target unit contracts are checked in CI.
- Existing dated reports and LDPS-Hardware provisioning records contain earlier bench evidence.
- Current `main` has not been re-established here against representative physical devices, live
  manufacturer credentials or every recovery path.
- A repository merge does not deploy the Station, contact a Cloud stage or flash hardware.

## Next checkpoint

Reconcile current recovery/security work and each open product pull request against the latest
cross-product identity decisions before product code is proposed for merge.
