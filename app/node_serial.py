"""USB serial link to a connected Edge-Node — identity provisioning + read-back.

The factory writes a node's identity over USB (NOT over the air); the node's
serial menu provides:
  'i'                          → info (UUID, Genuineness key_id/sig, FW, MAC, ...)
  'P <uuid> <sig> <key_id>'    → write identity (uuid + genuineness, write-once)

Blocking pyserial calls — call these via asyncio.to_thread() from async handlers.
"""
from __future__ import annotations

import re
import time

import serial  # pyserial (in requirements.txt)
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.utils import log

BAUD = 115200


def verify_node_identity_signature(uuid: str, signature: str, key_id: str,
                                   signing_keys: list) -> bool:
    """Verify the Cloud-minted Node identity before commit/resume."""
    key = next((item for item in signing_keys or [] if item.get("key_id") == key_id), None)
    if not key or key.get("algo", "ed25519") != "ed25519":
        return False
    try:
        public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(key["public_key"]))
        public_key.verify(bytes.fromhex(signature), uuid.encode("utf-8"))
        return True
    except (InvalidSignature, KeyError, TypeError, ValueError):
        return False


def _open(port: str, retries: int = 12, delay: float = 0.8) -> "serial.Serial":
    """Open the node serial port, retrying through the USB-CDC re-enumeration window.
    After an esptool flash the ESP32-S3 hard-resets (`--after hard_reset`) and its
    native USB-CDC port disappears for several seconds; a stale handle raises
    errno 19 ('Operation not supported by device') / SerialException. We retry for
    ~10s so the post-flash `format_sd` (and `read_identity`) don't spuriously fail."""
    last = None
    for _ in range(max(1, retries)):
        try:
            return serial.Serial(port, BAUD, timeout=0.3)
        except (serial.SerialException, OSError) as e:
            last = e
            time.sleep(delay)
    raise last if last is not None else serial.SerialException(f"cannot open {port}")


def _txn(port: str, send: str | None, wait: float = 1.6) -> str:
    """Open `port`, optionally write a line, read for `wait` seconds, return text.
    Reads past the node's interleaved periodic logs by accumulating the window."""
    with _open(port) as s:
        time.sleep(0.4)
        s.reset_input_buffer()
        if send is not None:
            s.write((send + "\n").encode())
            s.flush()
        end = time.time() + wait
        buf = b""
        while time.time() < end:
            buf += s.read(8192)
    return buf.decode(errors="replace")


def read_identity(port: str) -> dict:
    """Send 'i' and parse the node's identity fields."""
    t = _txn(port, "i")

    def grab(pat: str, default: str = "") -> str:
        m = re.search(pat, t)
        return m.group(1) if m else default

    return {
        "uuid": grab(r"UUID:\s*([0-9a-fA-F-]{36})"),
        "key_id": grab(r"key_id=(\S+?)\s"),
        "sig": grab(r"sig=([0-9a-fA-F]{128})").lower(),
        "fw": grab(r"FW:\s*(\S+)"),
        "mac": grab(r"MAC=([0-9A-Fa-f:]{17})"),
        "raw": t,
    }


def format_sd(port: str) -> dict:
    """Format the node's SD card to FAT32 via the node serial 'f' command (FatFS
    f_mkfs). Done right after a fresh flash so the production SD starts clean (the
    test rig always has the node on USB, so the serial path is fine). Returns
    {ok, detail}. Destructive — wipes the card; only used in the factory flash flow."""
    resp = _txn(port, "f", wait=8.0)  # f_mkfs on a large card + re-scan takes a few s
    if "Format OK" in resp:
        return {"ok": True, "detail": "FAT32 formatted"}
    if "SD not mounted" in resp:
        return {"ok": False, "detail": "SD not mounted — cannot format"}
    m = re.search(r"Format failed:.*", resp)
    return {"ok": False, "detail": m.group(0) if m else "no Format-OK ack"}


def clear_identity(port: str) -> dict:
    """Send 'U' to un-provision the node — clears uuid + genuineness sig + key_id +
    owner from NVS (NOT the SD). Node identity is write-once, so RE-provisioning a node
    that already has a UUID requires clearing it first. Returns {ok, detail}. Used by
    the RMA / re-provision path so the operator doesn't have to reflash just to re-mint."""
    resp = _txn(port, "U", wait=2.0)
    if "identity cleared" in resp:
        return {"ok": True, "detail": "identity cleared -> AWAIT_UUID"}
    return {"ok": False, "detail": "no clear ack: " + resp[-160:].strip()}


def _read_back_matches(port: str, expected_mac: str, uuid: str, sig: str, key_id: str,
                       attempts: int = 5) -> dict:
    """Re-read 'i' until the same node reports exactly {uuid, sig, key_id}. RETRIED: the very
    first read-back after 'P' sometimes comes back EMPTY (port close/reopen races the
    node's USB-CDC), which falsely failed a write that actually stuck."""
    ident = {}
    for _ in range(max(1, attempts)):
        ident = read_identity(port)
        if ((ident.get("mac") or "").upper() == expected_mac.upper()
                and ident.get("uuid") == uuid and ident.get("sig") == sig.lower()
                and ident.get("key_id") == key_id):
            return {"ok": True, "ident": ident}
        time.sleep(0.6)
    return {"ok": False, "ident": ident}


def _classify_uncertain_write(port: str, expected_mac: str, uuid: str, sig: str, key_id: str,
                              detail: str, attempts: int = 3) -> dict:
    """Resolve a lost response without deleting a possibly-written identity.

    A readable blank/different UUID on the same hardware MAC proves this new
    identity did not land and the Cloud reservation may be released. An exact
    match on the same MAC is success. A reused USB path or swapped board is
    ambiguous regardless of its contents. The
    same UUID with incomplete/different genuineness fields is a partial write;
    an unreadable device is ambiguous.  Both must retain the reservation.
    """
    last_ident: dict = {}
    readable = False
    last_error = ""
    for _ in range(max(1, attempts)):
        try:
            last_ident = read_identity(port)
            readable = bool(last_ident.get("mac"))
        except Exception as exc:
            last_error = str(exc)
            time.sleep(0.6)
            continue
        if ((last_ident.get("mac") or "").upper() == expected_mac.upper()
                and last_ident.get("uuid") == uuid
                and last_ident.get("sig") == sig.lower()
                and last_ident.get("key_id") == key_id):
            return {
                "ok": True,
                "uuid": uuid,
                "sig": sig,
                "key_id": key_id,
                "detail": "write response lost; exact read-back verified",
                "safe_to_release": False,
                "ambiguous": False,
            }
        time.sleep(0.6)

    actual_uuid = last_ident.get("uuid", "") if readable else ""
    same_device = readable and (last_ident.get("mac") or "").upper() == expected_mac.upper()
    if same_device and not actual_uuid:
        return {
            "ok": False,
            "detail": f"{detail}; readable node remains unprovisioned",
            "safe_to_release": True,
            "ambiguous": False,
            "ident": last_ident,
        }
    if same_device and actual_uuid != uuid:
        return {
            "ok": False,
            "detail": f"{detail}; node carries a different identity",
            "safe_to_release": True,
            "ambiguous": False,
            "ident": last_ident,
        }
    return {
        "ok": False,
        "detail": f"{detail}; identity outcome is ambiguous"
                  + (f" ({last_error})" if last_error else ""),
        "safe_to_release": False,
        "ambiguous": True,
        "ident": last_ident,
    }


def write_identity(port: str, expected_mac: str, uuid: str, sig: str, key_id: str) -> dict:
    """Send 'P <uuid> <sig> <key_id>', then read back 'i' to verify the node
    actually stored what we wrote. Returns {ok, uuid, sig, key_id, detail}.

    IDEMPOTENT ON RETRY: if the node refuses the write (its firmware rejects 'P' once a
    signature exists — including a retry of the SAME values after the ack line was lost),
    we read the identity back and treat an exact match as success. Without this, a lost
    '[PROV] identity written' line turned a fully-provisioned node into a false failure,
    the cloud reservation got released, and the unit was stranded (node refuses a
    different UUID forever)."""
    try:
        resp = _txn(port, f"P {uuid} {sig} {key_id}", wait=2.0)
    except Exception as exc:
        return _classify_uncertain_write(
            port, expected_mac, uuid, sig, key_id, f"USB write transport error: {exc}")
    prov_lines = [l.strip() for l in resp.splitlines() if "[PROV]" in l]
    if not any("identity written" in l for l in prov_lines):
        # Refused or no ack — the write may still have landed on an earlier attempt.
        outcome = _classify_uncertain_write(
            port, expected_mac, uuid, sig, key_id,
            "write refused/no acknowledgement", attempts=2)
        if outcome["ok"]:
            log(f"[NodeSerial] write refused/no-ack on {port} but read-back matches — "
                f"treating as already-written (idempotent retry)")
        return outcome
    try:
        rb = _read_back_matches(port, expected_mac, uuid, sig, key_id)
    except Exception as exc:
        return _classify_uncertain_write(
            port, expected_mac, uuid, sig, key_id,
            f"acknowledged write but read-back transport failed: {exc}")
    if rb["ok"]:
        return {"ok": True, "uuid": uuid, "sig": sig, "key_id": key_id,
                "detail": "read-back verified"}
    outcome = _classify_uncertain_write(
        port, expected_mac, uuid, sig, key_id,
        "read-back mismatch after acknowledged write")
    ident = outcome.get("ident", {})
    log(f"[NodeSerial] read-back mismatch on {port} after retries: "
        f"wrote uuid={uuid} kid={key_id}, read uuid={ident.get('uuid')} "
        f"kid={ident.get('key_id')} ambiguous={outcome.get('ambiguous')}", "ERROR")
    return outcome
