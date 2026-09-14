# Status — LDPS Provisioning Station

## Current reality

The working branch contains the factory Station application for LED Node and Control Hub
provisioning. It uses explicit Local, UAT and Production Cloud targets and rejects request-supplied
remote endpoint overrides. The repository does not deploy automatically.

The implemented operator surface contains automated Node and Hub flows. Node identity is written
over USB and committed to Cloud; Control Hub identity is written through its direct-local
provisioning channel and committed after restart/QC. Console Hub RF-bridge firmware is sent through
the assembled Control Hub. The factory Test Board supplies RF QC for LED Nodes.

An LED Node's temporary Desktop controller runtime role is not a separate product identity and is
never independently provisioned by this Station. The former standalone Desktop Hub Dongle
provisioning path has been removed from this branch.

## Verification boundary

- Repository structure, links and stage-target unit contracts are checked in CI.
- The recovery and security changes on this branch pass isolated software tests.
- Existing dated reports and LDPS-Hardware provisioning records contain earlier bench evidence.
- This branch has not been re-established against representative physical devices, live
  manufacturer credentials or every recovery path.
- A repository merge does not deploy the Station, contact a Cloud stage or flash hardware.

## Next checkpoint

Review the retained recovery and security changes against the latest cross-product identity
decisions, then use the normal pull-request path. Physical factory verification remains a separate,
attended step.
