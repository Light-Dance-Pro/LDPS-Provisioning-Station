# Status — LDPS Provisioning Station

The application supports factory flows for Edge Nodes and Control Hubs, plus a CLI-only Desktop Hub
Dongle flow. The Station uses manufacturer-key Cloud APIs, records local yield history, and reports
success only after the corresponding Cloud commit succeeds.

## Current boundaries

- Edge-Node identity is written over direct USB serial; identity writes are not RF operations.
- Control-Hub provisioning uses its direct-local provisioning channel and writes the SD identity
  binding; the Station does not flash the Orange Pi itself.
- Desktop Hub Dongle provisioning is CLI-only and expects approved firmware to be installed first.
- UAT does not mint product identities. New-unit and RMA issuance uses the owning factory authority.
- This repository has no automatic deployment. Physical provisioning claims require attended
  hardware evidence; software tests alone do not establish a completed factory run.

The checkout currently contains uncommitted implementation and test work. This status does not
promote that work to released or physically verified behavior.
