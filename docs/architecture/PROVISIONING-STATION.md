# Provisioning Station Architecture

## Purpose

The Station is a single factory application with different jobs for different LDPS devices. It
uses manufacturer credentials rather than Studio user authentication and coordinates Cloud,
direct-local device access and factory QC.

## Responsibility and authority

| Scope | Authority |
|---|---|
| Identity minting and signature | LDPS Cloud; private signing keys never belong on the Station |
| LED Node identity write | Station over USB serial; RF is used for QC, not identity mutation |
| Control Hub binding | Station obtains the signed binding and writes it through the direct-local provisioning channel |
| Console Hub RF bridge | Station asks the assembled Control Hub to flash the bridge on its USB connection |
| Cross-product hardware and identity decisions | LDPS-Hardware |
| Station implementation and operator behavior | This repository |

The code also calls the factory RF Test Board a dongle. That fixture and the Console Hub RF bridge
must not be confused with the temporary Desktop Hub Dongle runtime role of an LED Node.

## LED Node flow

The operator starts one automated sequence after readiness checks. The Station flashes the Node,
formats its SD card, discovers it over USB, runs hardware and visual checks with the Test Board,
requests a Cloud-signed identity, writes it over USB and commits the result to Cloud. A lost
acknowledgement must not cause a matching already-written identity to be replaced.

## Control Hub flow

The Station reads the assembled Hub identity through the direct-local channel, obtains its signed
binding, sends the Hub program and Console Hub RF-bridge firmware, writes the binding, commits it,
restarts the Hub and verifies its control-plane health. The Station does not flash the Orange Pi
storage image itself.

## Security boundary

- The manufacturer API key authorizes factory operations and is distinct from Studio or Hub auth.
- UAT and Production endpoint selection is stage-controlled; an operator request cannot substitute
  an arbitrary remote host.
- Identity mutation uses direct-local transports, never RF or a public Internet control path.
- Provisioning success is reported only after the corresponding Cloud commit succeeds.

## Cross-product sources

- [Provisioning map](https://github.com/Light-Dance-Pro/LDPS-Hardware/blob/main/docs/architecture/provisioning/README.md)
- [Node identity ownership](https://github.com/Light-Dance-Pro/LDPS-Hardware/blob/main/docs/architecture/provisioning/PROVISION_IDENTITY_OWNERSHIP_DESIGN.md)
- [Control Hub identity](https://github.com/Light-Dance-Pro/LDPS-Hardware/blob/main/docs/architecture/provisioning/HUB_IDENTITY_DESIGN.md)
- [Manufacturer API key decision](https://github.com/Light-Dance-Pro/LDPS-Hardware/blob/main/docs/decisions/ADR-004-MANUFACTURER-API-KEY-AUTH.md)
