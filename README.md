# LDPS Provisioning Station

Factory production-line application for provisioning and quality-control testing of LDPS devices.
It uses manufacturer credentials, not Studio or Supabase user authentication, and has no automatic
deployment.

## Start here

- [STATUS.md](STATUS.md) — current implementation and verification boundary.
- [docs/index.md](docs/index.md) — durable product documentation and repository conventions.
- [Provisioning Station architecture](docs/architecture/PROVISIONING-STATION.md) — device roles,
  authority and operating flows.

## Runtime

The FastAPI application starts from `main.py` and serves the factory interface. `LDPS_STAGE` is
required and selects exactly one of `local`, `uat`, or `prod`; the Local profile may use a
workstation-specific Cloud URL.

## Device responsibilities

| Device | Station responsibility | Primary transport |
|---|---|---|
| LED Node | Flash firmware, obtain a Cloud-signed identity, write it over USB, commit it to Cloud and run RF/playback QC | USB serial plus the factory Test Board |
| Control Hub | Read hardware identity, register it, write the signed SD binding, restart and perform functional QC | Direct-local provisioning channel |
| Console Hub Dongle | Ask the assembled Control Hub to flash its RF-bridge firmware | Control Hub local channel |

An LED Node may temporarily perform the Desktop controller runtime role after a live Desktop Hub
claim. That role is not a separately provisioned product identity and has no dedicated Station
provisioning path.
