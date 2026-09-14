# Status — LDPS Provisioning Station

The application supports factory flows for LED Nodes and Control Hubs. It also sends the Console
Hub Dongle RF-bridge firmware through an assembled Control Hub. The Station uses manufacturer-key
Cloud APIs, records local yield history, and reports success only after the corresponding Cloud
commit succeeds.

## Current boundaries

- LED Node identity is written over direct USB serial; identity writes are not RF operations.
- Control-Hub provisioning uses its direct-local provisioning channel and writes the SD identity
  binding; the Station does not flash the Orange Pi itself.
- An LED Node's temporary Desktop controller runtime role is not a separate product identity and is
  never independently provisioned by this Station.
- UAT does not mint product identities. New-unit and RMA issuance uses the owning factory authority.
- This repository has no automatic deployment. Physical provisioning claims require attended
  hardware evidence; software tests alone do not establish a completed factory run.

The working branch contains software-verified recovery and security hardening for the existing LED
Node and Control Hub flows. It has not been merged, deployed or re-established against physical
factory devices, live manufacturer credentials or every recovery path.
