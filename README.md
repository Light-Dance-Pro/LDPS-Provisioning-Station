# LDPS Provisioning Station

Factory production-line application for provisioning and quality-control testing of LDPS devices.
It uses manufacturer credentials, not Studio or Supabase user authentication, and has no automatic
deployment.

## Repository navigation

- [STATUS.md](STATUS.md) — current supported device flows and verification boundary.
- [docs/index.md](docs/index.md) — component documentation map and owning platform design links.

## Runtime

The FastAPI application starts from `main.py` and serves the factory interface. `LDPS_STAGE` is
required and selects exactly one of `local`, `uat`, or `prod`; the Local profile may use a
workstation-specific Cloud URL.

The implementation contains separate paths for Edge-Node, Control-Hub, and Desktop Hub Dongle
provisioning. Device identity is written only through the relevant direct-local transport; the
Cloud remains the identity-minting and signing authority.
