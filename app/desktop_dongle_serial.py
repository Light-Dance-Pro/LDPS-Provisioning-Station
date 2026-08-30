"""Direct-USB factory identity transport for the Desktop Hub Dongle."""
from __future__ import annotations

import re
import time
import uuid

import serial
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

BAUD = 115200
IDENTITY_VERSION = 1
IDENTITY_DOMAIN = "ldps:desktop-hub-dongle"


def normalize_fingerprint(value: str) -> str:
    normalized = re.sub(r"[^0-9A-F]", "", str(value or "").upper())
    return normalized if re.fullmatch(r"[0-9A-F]{12}", normalized) else ""


def identity_message(hub_uuid: str, hardware_fingerprint: str) -> bytes:
    fingerprint = normalize_fingerprint(hardware_fingerprint)
    try:
        canonical_uuid = str(uuid.UUID(str(hub_uuid or "")))
    except (ValueError, AttributeError):
        canonical_uuid = ""
    if not canonical_uuid or not fingerprint:
        raise ValueError("invalid Desktop Hub Dongle identity")
    return f"{IDENTITY_DOMAIN}:v{IDENTITY_VERSION}:{canonical_uuid}:{fingerprint}".encode()


def verify_identity_signature(
    hub_uuid: str,
    hardware_fingerprint: str,
    signature: str,
    key_id: str,
    signing_keys: list,
) -> bool:
    key = next((item for item in signing_keys if item.get("key_id") == key_id), None)
    if not key or key.get("algo") != "ed25519":
        return False
    try:
        public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(key["public_key"]))
        public_key.verify(bytes.fromhex(signature), identity_message(hub_uuid, hardware_fingerprint))
        return True
    except (InvalidSignature, ValueError, TypeError, KeyError):
        return False


def _open(port: str, retries: int = 8, delay: float = 0.5) -> "serial.Serial":
    last_error = None
    for _ in range(max(1, retries)):
        try:
            return serial.Serial(port, BAUD, timeout=0.25)
        except (serial.SerialException, OSError) as exc:
            last_error = exc
            time.sleep(delay)
    raise last_error or serial.SerialException(f"cannot open {port}")


def _txn(port: str, command: str, wait: float = 1.5) -> str:
    with _open(port) as link:
        time.sleep(0.25)
        link.reset_input_buffer()
        link.write((command + "\n").encode())
        link.flush()
        end = time.time() + wait
        response = b""
        while time.time() < end:
            response += link.read(2048)
    return response.decode(errors="replace")


def _last_payload(raw: str, prefix: str) -> str:
    matches = re.findall(rf"(?im)^dg:{re.escape(prefix)}([^\r\n]*)", raw)
    return matches[-1].strip() if matches else ""


def _fields(payload: str) -> dict:
    result = {}
    for item in payload.split(","):
        if "=" in item:
            key, value = item.split("=", 1)
            result[key.strip()] = value.strip()
    return result


def read_status(port: str) -> dict:
    raw = _txn(port, "DG:STATUS")
    payload = _last_payload(raw, "READY,")
    fields = _fields(payload)
    return {
        "ok": bool(payload),
        "firmware_ver": fields.get("version", ""),
        "sx1262": fields.get("sx1262", ""),
        "espnow": fields.get("espnow", ""),
        "hardware_fingerprint": normalize_fingerprint(fields.get("mac", "")),
        "raw": raw,
    }


def read_identity(port: str) -> dict:
    raw = _txn(port, "DG:IDENTITY")
    payload = _last_payload(raw, "IDENTITY,")
    fields = _fields(payload)
    provisioned = fields.get("provisioned") == "1"
    try:
        identity_version = int(fields.get("iv", "0") or 0)
    except (TypeError, ValueError):
        identity_version = None
    error = fields.get("error", "")
    if identity_version is None and not error:
        error = "invalid_identity_version"
    return {
        "ok": bool(payload) and not error,
        "provisioned": provisioned,
        "identity_version": identity_version,
        "hub_uuid": fields.get("uuid", ""),
        "hardware_fingerprint": normalize_fingerprint(fields.get("fingerprint", "")),
        "key_id": fields.get("kid", ""),
        "signature": fields.get("sig", "").lower(),
        "error": error,
        "raw": raw,
    }


def _identity_matches(actual: dict, expected: dict) -> bool:
    return (
        actual.get("provisioned")
        and actual.get("identity_version") == IDENTITY_VERSION
        and actual.get("hub_uuid", "").lower() == expected["hub_uuid"].lower()
        and actual.get("hardware_fingerprint") == expected["hardware_fingerprint"]
        and actual.get("key_id") == expected["key_id"]
        and actual.get("signature") == expected["signature"].lower()
    )


def write_identity(port: str, identity: dict, attempts: int = 4) -> dict:
    expected = {
        "hub_uuid": str(identity["hub_uuid"]).lower(),
        "hardware_fingerprint": normalize_fingerprint(identity["hardware_fingerprint"]),
        "key_id": str(identity["key_id"]),
        "signature": str(identity["identity_signature"]).lower(),
    }
    command = (
        f"DG:PROVISION,{IDENTITY_VERSION},{expected['hub_uuid']},"
        f"{expected['hardware_fingerprint']},{expected['key_id']},{expected['signature']}"
    )
    raw = _txn(port, command, wait=2.0)
    ack = _last_payload(raw, "PROVISION,")

    actual = {}
    for _ in range(max(1, attempts)):
        actual = read_identity(port)
        if _identity_matches(actual, expected):
            return {"ok": True, "identity": actual, "detail": "exact readback verified"}
        time.sleep(0.4)

    error_match = re.search(r"(?im)^dg:PROVISION,err,([^\r\n,]+)", raw)
    code = error_match.group(1) if error_match else "no_exact_readback"
    deterministic_rejection = code in {
        "already_provisioned",
        "fingerprint_mismatch",
        "bad_args",
        "bad_version",
        "bad_uuid",
        "bad_fingerprint",
        "bad_key_id",
        "bad_signature",
    }
    # A valid identity response is authoritative for this device. If it does not
    # match the reservation after every retry, the reserved identity was not
    # written and can be released. An unreadable response remains ambiguous and
    # must be retained for --resume rather than risking a second identity.
    readback_proves_not_written = bool(actual.get("ok"))
    return {
        "ok": False,
        "code": code,
        "safe_to_release": deterministic_rejection or readback_proves_not_written,
        "identity": actual,
        "detail": ack or raw[-200:].strip(),
    }
