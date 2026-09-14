# LDPS Provisioning Station

Factory production-line application for provisioning and quality-checking LDPS devices. It uses a
manufacturer API key to communicate with LDPS Cloud and has no automatic deployment from this
repository.

## Start here

- [STATUS.md](STATUS.md) — current implementation and verification boundary.
- [docs/index.md](docs/index.md) — durable product documentation and repository conventions.
- [Provisioning Station architecture](docs/architecture/PROVISIONING-STATION.md) — device roles,
  authority and operating flows.

## Device responsibilities

| Device | Station responsibility | Primary transport |
|---|---|---|
| LED Node | Flash firmware, obtain a Cloud-signed identity, write it over USB, commit it to Cloud and run RF/playback QC | USB serial plus the factory Test Board |
| Control Hub | Read hardware identity, register it, write the signed SD binding, restart and perform functional QC | Direct-local provisioning channel |
| Console Hub Dongle | Ask the assembled Control Hub to flash its RF-bridge firmware | Control Hub local channel |

An LED Node may temporarily perform the Desktop controller runtime role after a live Desktop Hub
claim. That role is not a separately provisioned product identity and has no dedicated Station
provisioning path. The factory Test Board and the Console Hub's RF bridge are separate devices.

## Development

```bash
python3 -m pip install -r requirements.txt
LDPS_STAGE=local PORT=9000 python3 main.py
```

`LDPS_STAGE` is required and accepts only `local`, `uat` or `prod`. UAT and Production use their
canonical Cloud API hosts; only the Local profile can override its workstation URL.

Run repository checks with:

```bash
python3 -m unittest tests.test_docs_lint tests.test_repo_lint tests.test_stage_targets
python3 tools/docs_lint.py
python3 tools/repo_lint.py
```

These checks do not provision hardware, contact a live Cloud stage or flash a device.

## Repository map

- `main.py`, `app/`, `templates/` and `static/` — FastAPI operator application and local assets.
- `flash_boot/` — checked-in LED Node boot image components used by the station.
- `tools/` — local generation, test and repository-check utilities.
- `tests/` — isolated software contracts.
- `docs/` — durable strategy, architecture, decisions, reference, procedures and evidence.

Cross-product identity and provisioning authority is owned by
[LDPS-Hardware](https://github.com/Light-Dance-Pro/LDPS-Hardware/tree/main/docs/architecture/provisioning).
This repository owns the Station implementation and Station-specific documentation.
