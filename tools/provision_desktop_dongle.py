#!/usr/bin/env python3
"""Provision a Desktop Hub Dongle over direct USB, without adding Station UI."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.cloud_client import CloudClient
from app.config import DEFAULT_CLOUD_URL, LDPS_STAGE_RESOLVED, STATIC_DIR
from app.desktop_dongle_serial import (
    read_identity,
    read_status,
    verify_identity_signature,
    write_identity,
)

DEFAULT_PRODUCT = "Desktop Hub Dongle"


def manufacturer_key() -> str:
    from_env = os.environ.get("LDPS_MANUFACTURER_KEY", "").strip()
    if from_env:
        return from_env
    session_path = Path(STATIC_DIR) / "mfr_session.json"
    try:
        return str(json.loads(session_path.read_text()).get("api_key", "")).strip()
    except (OSError, ValueError):
        return ""


def print_identity(identity: dict) -> None:
    print(f"Dongle UUID: {identity.get('hub_uuid', '—')}")
    print(f"Fingerprint: {identity.get('hardware_fingerprint', '—')}")
    print(f"Signing key: {identity.get('key_id', '—')}")


async def run(args: argparse.Namespace) -> int:
    print(f"Cloud stage: {LDPS_STAGE_RESOLVED} ({DEFAULT_CLOUD_URL})")
    status = read_status(args.port)
    if not status["ok"] or not status["hardware_fingerprint"]:
        print("ERROR: the port did not return a valid DG:STATUS / ESP32 fingerprint")
        return 2
    if status["sx1262"] != "ok":
        print(f"ERROR: SX1262 QC failed (reported {status['sx1262'] or 'unknown'})")
        return 2
    if status["espnow"] != "ok":
        print(f"ERROR: ESP-NOW QC failed (reported {status['espnow'] or 'unknown'})")
        return 2

    current = read_identity(args.port)
    if current.get("hardware_fingerprint") != status["hardware_fingerprint"]:
        print("ERROR: DG:STATUS and DG:IDENTITY reported different hardware fingerprints")
        return 2

    api_key = manufacturer_key()
    if not api_key:
        print("ERROR: no manufacturer session; log in to this Station stage or set LDPS_MANUFACTURER_KEY")
        return 2
    cloud = CloudClient(DEFAULT_CLOUD_URL)
    login = await cloud.login(api_key)
    if not login.get("ok"):
        print(f"ERROR: manufacturer login failed: {login.get('error', 'unknown error')}")
        return 3

    if args.resume:
        if not current.get("provisioned"):
            print("ERROR: --resume requires a Dongle that already contains an identity")
            return 2
        keys = await cloud.get_signing_keys()
        if not verify_identity_signature(
            current["hub_uuid"],
            current["hardware_fingerprint"],
            current["signature"],
            current["key_id"],
            keys,
        ):
            print("ERROR: the existing Dongle identity does not verify against this Cloud's public keys")
            return 4
        confirm = await cloud.confirm_desktop_dongle(current["hub_uuid"], success=True)
        if not confirm["ok"]:
            print(f"ERROR: Cloud confirm failed ({confirm['status']}): {confirm['error']}")
            return 5
        print("Provisioning resumed and Cloud commit confirmed.")
        print_identity(current)
        return 0

    if current.get("provisioned"):
        print("ERROR: Dongle is already provisioned; use --resume to verify and retry Cloud commit")
        print_identity(current)
        return 2

    response = await cloud.provision_desktop_dongle(
        status["hardware_fingerprint"],
        args.product,
        test_results={
            "usb_serial": True,
            "sx1262": status["sx1262"] == "ok",
            "espnow": status["espnow"] == "ok",
        },
        firmware_ver=status["firmware_ver"],
        provision_batch=args.batch,
    )
    if not response.get("ok"):
        print(f"ERROR: Cloud reservation failed: {response.get('error', 'unknown error')}")
        return 3

    if not verify_identity_signature(
        response["hub_uuid"],
        response["hardware_fingerprint"],
        response["identity_signature"],
        response["key_id"],
        response.get("signing_keys", []),
    ):
        print("ERROR: Cloud returned an identity signature that failed local verification")
        return 4

    written = write_identity(args.port, response)
    if not written["ok"]:
        if written.get("safe_to_release"):
            released = await cloud.confirm_desktop_dongle(response["hub_uuid"], success=False)
            release_note = "reservation released" if released["ok"] else "reservation release failed"
        else:
            release_note = "reservation retained for --resume because the USB outcome is ambiguous"
        print(f"ERROR: Dongle write/readback failed ({written.get('code')}): {release_note}")
        return 5

    confirm = await cloud.confirm_desktop_dongle(response["hub_uuid"], success=True)
    if not confirm["ok"]:
        print("ERROR: identity is written and locally verified, but Cloud commit failed; rerun with --resume")
        print_identity(written["identity"])
        return 5

    print("Desktop Hub Dongle provisioned and Cloud commit confirmed.")
    print_identity(written["identity"])
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="Dongle serial port, e.g. /dev/cu.usbmodem101")
    parser.add_argument("--product", default=DEFAULT_PRODUCT, help="Catalog product key")
    parser.add_argument("--batch", default="", help="Optional production batch reference")
    parser.add_argument("--resume", action="store_true", help="Verify the existing Dongle identity and retry Cloud commit")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
