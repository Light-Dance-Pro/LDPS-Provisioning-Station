"""Provisioning workflow routes."""
from __future__ import annotations

import asyncio
import json
import time
import threading
from threading import Event

from fastapi import APIRouter, Request, Body
from fastapi.responses import JSONResponse

from app.config import IDENTITY_MINTING_ALLOWED
from app.utils import log

router = APIRouter()

# Pending ACK trackers with TTL cleanup
_pending_hw_test: dict[str, dict] = {}
_pending_status: dict[str, dict] = {}
_PENDING_TTL = 30  # seconds before auto-cleanup


def _cleanup_stale(d: dict[str, dict]) -> None:
    """Remove entries older than _PENDING_TTL seconds."""
    now = time.time()
    stale = [k for k, v in d.items() if now - v.get("ts", 0) > _PENDING_TTL]
    for k in stale:
        d.pop(k, None)


def _s(r: Request):
    return r.app.state.app_state


# ── ESP-NOW Response Handlers (called from __init__.py) ────

def handle_hw_test_nack(mac: str, reason: str) -> None:
    """Node refused HW_TEST (HW_TEST_ACK,err,<reason>) — fail the wait immediately
    with the reason instead of letting it die as a 15s timeout."""
    pending = _pending_hw_test.get(mac)
    if pending:
        pending["result"] = {"refused": reason}
        pending["event"].set()


def handle_hw_test_result(mac: str, parts: list[str]) -> None:
    json_str = ",".join(parts[1:]) if len(parts) > 1 else "{}"
    try:
        result = json.loads(json_str)
    except Exception:
        result = {"raw": json_str}
    pending = _pending_hw_test.get(mac)
    if pending:
        pending["result"] = result
        pending["event"].set()


def handle_status_rsp(mac: str, payload: str) -> None:
    """Handle STATUS_RSP for NVS read-back verification."""
    pending = _pending_status.get(mac)
    if pending:
        # Parse key=value pairs
        kv = {}
        for part in payload.split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                kv[k] = v
        pending["result"] = kv
        pending["event"].set()


# ── Discovery ─────────────────────────────────────────

@router.post("/discover")
async def discover(request: Request):
    s = _s(request)
    if not s.espnow:
        return JSONResponse({"error": "Dongle not connected"}, 503)

    s.discovered_nodes.clear()
    s.espnow.discover()

    # Wait 3 seconds for responses — async sleep: a time.sleep here stalled the whole
    # event loop (every other HTTP/WS request) for the discovery window.
    await asyncio.sleep(3)

    nodes = list(s.discovered_nodes.values())
    return {"ok": True, "nodes": nodes}


@router.post("/identify/{mac}")
async def identify(request: Request, mac: str):
    s = _s(request)
    if not s.espnow:
        return JSONResponse({"error": "Dongle not connected"}, 503)
    s.espnow.identify(mac)
    return {"ok": True}


# ── Hardware Test ─────────────────────────────────────

@router.post("/hw-test/{mac}")
async def hw_test(request: Request, mac: str):
    s = _s(request)
    if not s.espnow:
        return JSONResponse({"error": "Dongle not connected"}, 503)

    _cleanup_stale(_pending_hw_test)
    evt = Event()
    _pending_hw_test[mac] = {"event": evt, "result": None, "ts": time.time()}

    try:
        s.espnow.hw_test(mac)
        # evt is set from the dongle RX thread; wait in a worker thread so the
        # event loop keeps serving (a bare evt.wait blocked ALL requests for 15s).
        if not await asyncio.to_thread(evt.wait, 15):
            return JSONResponse({"error": "HW_TEST timeout"}, 408)
        result = _pending_hw_test[mac].get("result")
        if isinstance(result, dict) and result.get("refused"):
            return JSONResponse({"error": f"HW_TEST refused by node: {result['refused']}"}, 409)
        return {"ok": True, "mac": mac, "test_results": result}
    finally:
        _pending_hw_test.pop(mac, None)


# ── Finalize (USB provision: cloud UUID + genuineness → write over USB) ──

_RETRYABLE_HTTP = (0, 500, 502, 503, 504)   # 0 = network error


async def _confirm_commit(s, uuid: str, attempts: int = 3) -> dict:
    """Commit (reserved → provisioned) with bounded retries on transient failures.
    Terminal 4xx (404 missing record, 409 wrong lifecycle) returns
    immediately — retrying those can never succeed."""
    last = {"ok": False, "status": 0, "error": "not attempted"}
    for attempt in range(max(1, attempts)):
        last = await s.cloud_client.confirm(uuid, success=True)
        if last["ok"] or last["status"] not in _RETRYABLE_HTTP:
            return last
        await asyncio.sleep(1.5 * (attempt + 1))
    return last


def _log_success(s, mac: str, uuid: str, product: str, firmware_ver: str,
                 test_results, recovery_key: str) -> None:
    from app.provision_log import ProvisionLog
    if not getattr(s, "provision_log", None):
        s.provision_log = ProvisionLog()
    s.provision_log.add(
        mac=mac, uuid=uuid, product_type=product,
        firmware_ver=firmware_ver or "?", test_results=test_results,
        status="success", cloud_confirmed=True,
        manufacturer_id=getattr(getattr(s, "cloud_client", None), "manufacturer_id", ""),
    )
    s.stats_provisioned += 1
    if s.ws:
        s.ws.broadcast("stats", {"provisioned": s.stats_provisioned, "failed": s.stats_failed})
        s.ws.broadcast("provision", {"step": "done", "mac": mac, "uuid": uuid,
                                     "recovery_key": recovery_key})


@router.post("/finalize/{mac}")
async def finalize(request: Request, mac: str, data: dict = Body(...)):
    """USB provision: cloud request-uuid (uuid + Ed25519 genuineness signature) →
    write identity to the node over USB serial ('P') + read-back verify → cloud
    confirm. The dongle is NOT used for identity (that's USB) — only for RF QC
    (/hw-test). `mac` is the node's hardware id (cloud hardware_serial); the body
    carries the USB `port`, `product` (required QC gate), `test_results`,
    `firmware_ver`.

    RE-ENTRANT: success is only reported after the cloud commit lands. If the node was
    already written (a previous attempt whose commit failed), a retry RESUMES the commit
    for the node's own UUID instead of minting a new one — so 'Retry' after any network
    blip converges to done, and the unit is never left half-committed silently."""
    from app.node_serial import (
        write_identity,
        read_identity,
        verify_node_identity_signature,
    )

    s = _s(request)
    if not IDENTITY_MINTING_ALLOWED:
        return JSONResponse({
            "error": "UAT is for application QA and stage enrollment; it cannot mint or commit "
                     "product identity. Switch the Provisioning Station to Production factory mode.",
            "code": "IDENTITY_AUTHORITY_DISABLED",
        }, 403)
    if not getattr(s, "cloud_client", None):
        return JSONResponse({"error": "Not logged in to Cloud"}, 401)

    port = data.get("port")
    product = data.get("product")   # the catalog product key (ADR-0008)
    test_results = data.get("test_results")
    firmware_ver = data.get("firmware_ver", "")
    # recovery_key from a previous attempt of THIS unit (the UI passes it back on Retry
    # so the resumed success can still print the box label).
    prior_recovery_key = data.get("recovery_key") or ""
    if not port:
        return JSONResponse({"error": "port required (node USB serial port)"}, 400)
    if not product:
        return JSONResponse({"error": "product required (QC gate)"}, 400)

    # P1 GUARD — USB is the AUTHORITATIVE identity channel: it is the link we actually
    # write to, whereas the RF-discovered `mac` is a separate node that merely answered
    # over the air. Read the node on `port` over USB FIRST and verify it is the selected
    # node, BEFORE minting/writing — else a UUID minted for MAC-A could be written into
    # node-B on the wrong port (cloud serial ≠ the node's real MAC).
    ident = await asyncio.to_thread(read_identity, port)
    usb_mac = (ident.get("mac") or "").upper()
    if not usb_mac:
        return JSONResponse({"error": f"No node responding on {port} — check the USB cable/port."}, 409)
    if mac and usb_mac != mac.upper():
        return JSONResponse({"error": f"Wrong node on {port}: USB MAC {usb_mac} ≠ selected {mac.upper()}. "
                                      f"Select the USB port of the node you discovered.", "code": "MAC_MISMATCH"}, 409)
    hw_serial = usb_mac

    if ident.get("uuid"):
        # Node already carries an identity. RESUME is allowed ONLY for the uuid THIS
        # flow minted (the UI passes it back as `resume_uuid` on Retry) — a previous
        # attempt wrote the node but the cloud commit was lost, so finish the commit
        # (idempotent server-side). Any OTHER identity is foreign: never silently
        # adopt it — the operator must Clear first.
        uuid = ident["uuid"]
        if data.get("resume_uuid") == uuid:
            signing_keys = await s.cloud_client.get_signing_keys()
            identity_complete = bool(ident.get("sig") and ident.get("key_id"))
            identity_verified = identity_complete and verify_node_identity_signature(
                uuid, ident.get("sig", ""), ident.get("key_id", ""), signing_keys)
            if identity_verified:
                c = await _confirm_commit(s, uuid)
                if c["ok"]:
                    _log_success(s, mac, uuid, product, firmware_ver, test_results, prior_recovery_key)
                    log(f"[Provision] RESUMED commit (USB): {mac} → {uuid}")
                    return {"ok": True, "mac": mac, "uuid": uuid, "key_id": ident.get("key_id"),
                            "recovery_key": prior_recovery_key, "cloud_confirmed": True,
                            "resumed": True}
                if c["status"] in _RETRYABLE_HTTP:
                    return JSONResponse({"error": f"Node is written (UUID {uuid}) but the cloud commit "
                                                  f"is unreachable ({c['error']}). Retry when the network is back "
                                                  f"— Retry resumes this unit, it does not re-mint.",
                                         "code": "CONFIRM_RETRYABLE", "uuid": uuid,
                                         "recovery_key": prior_recovery_key}, 502)
                return JSONResponse({"error": f"The cloud refuses the commit for {uuid} "
                                              f"({c['error'] or 'no record'} — missing or invalid lifecycle). "
                                              f"Do not provision another unit with this record; set this unit aside "
                                              f"for an audited RMA clear.",
                                     "code": "CONFIRM_TERMINAL", "uuid": uuid,
                                     "recovery_key": prior_recovery_key}, 409)

            # A power loss can leave UUID written before the genuineness fields.
            # Re-request the same reservation and finish the idempotent P write;
            # never commit a UUID merely because it matches the UI's memory.
            minted = await s.cloud_client.request_uuid(
                hw_serial, product, test_results, firmware_ver)
            if not minted or minted.get("uuid") != uuid:
                return JSONResponse({
                    "error": "Node has a partial identity, but Cloud no longer returns the same reservation. "
                             "Keep the unit out of production and use the audited RMA recovery path.",
                    "code": "PARTIAL_IDENTITY_ORPHANED",
                    "uuid": uuid,
                    "recovery_key": prior_recovery_key,
                }, 409)
            sig = minted.get("signature") or ""
            key_id = minted.get("key_id") or ""
            recovery_key = minted.get("recovery_key") or prior_recovery_key
            if ((ident.get("sig") and ident.get("sig") != sig.lower())
                    or (ident.get("key_id") and ident.get("key_id") != key_id)):
                return JSONResponse({
                    "error": "Node carries partial genuineness data that does not match the Cloud reservation. "
                             "Do not commit it; use the audited RMA recovery path.",
                    "code": "PARTIAL_IDENTITY_CONFLICT",
                    "uuid": uuid,
                    "recovery_key": recovery_key,
                }, 409)
            if not sig or not key_id or not verify_node_identity_signature(
                    uuid, sig, key_id, signing_keys):
                return JSONResponse({
                    "error": "Cloud identity signature could not be verified; nothing was committed.",
                    "code": "SIGNATURE_UNVERIFIED",
                    "uuid": uuid,
                    "recovery_key": recovery_key,
                }, 502)
            # Continue into the common write/read-back/commit path below.
        else:
            return JSONResponse({"error": f"Node already provisioned (UUID {uuid}). "
                                          f"Clear its identity (Re-provision) before writing a new one.",
                                 "code": "ALREADY_PROVISIONED"}, 409)
    else:
        # Step 1: mint UUID + genuineness signature from Cloud.
        minted = await s.cloud_client.request_uuid(hw_serial, product, test_results, firmware_ver)
        if not minted or not minted.get("uuid"):
            return JSONResponse({"error": "Failed to get UUID from Cloud"}, 502)
        uuid = minted["uuid"]
        sig = minted.get("signature") or ""
        key_id = minted.get("key_id") or ""
        # recovery_key: returned ONCE by the cloud (plaintext), never written to the node — the
        # operator prints it on the box for re-claim (§3.4). It is surfaced only to
        # the active UI flow; production history must not become a second plaintext
        # recovery-credential store.
        recovery_key = minted.get("recovery_key") or ""
        signing_keys = await s.cloud_client.get_signing_keys()
        if not sig or not key_id or not verify_node_identity_signature(
                uuid, sig, key_id, signing_keys):
            # Nothing has been written to hardware, so this release is deterministic.
            await s.cloud_client.confirm(uuid, success=False)
            return JSONResponse({
                "error": "Cloud identity signature could not be verified; reservation released.",
                "code": "SIGNATURE_UNVERIFIED",
            }, 502)

    # Step 2: write identity to the node over USB + read-back verify (blocking → thread).
    if s.ws:
        s.ws.broadcast("provision", {"step": "writing", "mac": mac, "uuid": uuid})
    try:
        w = await asyncio.to_thread(write_identity, port, hw_serial, uuid, sig, key_id)
    except Exception as e:
        # The P command may have reached NVS before the USB exception.  Releasing
        # here can orphan a write-once physical identity, so retain the reservation.
        return JSONResponse({
            "error": f"USB write outcome is ambiguous on {port}: {e}. Reconnect the same unit and Retry.",
            "code": "WRITE_AMBIGUOUS",
            "uuid": uuid,
            "recovery_key": recovery_key,
        }, 502)
    if not w.get("ok"):
        if w.get("safe_to_release"):
            rel = await s.cloud_client.confirm(uuid, success=False)
            if not rel["ok"]:
                log(f"[Provision] release failed for {uuid} after proven no-write "
                    f"({rel['error']})", "WARNING")
            return JSONResponse({
                "error": f"Node identity write failed before landing: {w.get('detail')}",
                "code": "WRITE_NOT_APPLIED",
            }, 500)
        return JSONResponse({
            "error": f"Node identity write outcome is ambiguous: {w.get('detail')}. "
                     "The reservation was retained; reconnect this same unit and Retry.",
            "code": "WRITE_AMBIGUOUS",
            "uuid": uuid,
            "recovery_key": recovery_key,
        }, 502)

    # Step 3: confirm with Cloud (reserved → provisioned) — success is gated on this.
    c = await _confirm_commit(s, uuid)
    if not c["ok"]:
        log(f"[Provision] commit failed for {uuid} — identity IS written "
            f"(status={c['status']} {c['error']})", "ERROR")
        code = "CONFIRM_RETRYABLE" if c["status"] in _RETRYABLE_HTTP else "CONFIRM_TERMINAL"
        hint = ("Retry resumes this unit (no re-mint)." if code == "CONFIRM_RETRYABLE"
                else "The identity record is missing or in an invalid lifecycle. Keep the unit out of production "
                     "and use the audited RMA clear path; do not re-mint another unit from this record.")
        return JSONResponse({"error": f"Identity written to the node, but the cloud commit failed: "
                                      f"{c['error'] or ('HTTP ' + str(c['status']))}. {hint}",
                             "code": code, "uuid": uuid, "recovery_key": recovery_key}, 502)

    _log_success(s, mac, uuid, product, firmware_ver, test_results, recovery_key)
    log(f"[Provision] SUCCESS (USB): {mac} → {uuid} (key_id={key_id})")  # recovery_key NOT logged
    return {"ok": True, "mac": mac, "uuid": uuid, "key_id": key_id,
            "recovery_key": recovery_key, "cloud_confirmed": True}


# ── QC fail recording (ST3 / DR-13) — the yield gate ─────────
# report_test_fail() was dead code, so a unit that failed HW_TEST / playback / the
# USB write was never counted (stats_failed never moved → yield always 100%). The
# operator records a failed unit here: cloud test-fail (NO quota burn) + stats_failed++
# + a 'failed' provision_log row. Explicit (operator's final verdict) so retrying a
# flaky test doesn't double-count; the GUI offers "Set aside as failed" on any fail.

async def _record_fail(s, mac: str, reason: str, test_results: dict = None,
                       product_type: str = "", firmware_ver: str = "") -> None:
    if getattr(s, "cloud_client", None):
        try:
            await s.cloud_client.report_test_fail(mac, test_results, reason)
        except Exception as e:
            log(f"[Provision] report_test_fail error: {e}", "WARNING")
    from app.provision_log import ProvisionLog
    if not getattr(s, "provision_log", None):
        s.provision_log = ProvisionLog()
    try:
        s.provision_log.add(mac=mac, uuid=None, product_type=product_type or "?",
                            firmware_ver=firmware_ver or "?", test_results=test_results,
                            status="failed", error_reason=reason,
                            manufacturer_id=getattr(getattr(s, "cloud_client", None), "manufacturer_id", ""))
    except Exception as e:
        log(f"[Provision] provision_log(failed) error: {e}", "WARNING")
    s.stats_failed += 1
    if s.ws:
        s.ws.broadcast("stats", {"provisioned": s.stats_provisioned, "failed": s.stats_failed})
    log(f"[Provision] FAIL recorded: {mac} — {reason}")


@router.post("/report-fail/{mac}")
async def report_fail(request: Request, mac: str, data: dict = Body(default={})):
    """Operator sets a unit aside as QC-failed (after a failed HW test / playback /
    write). Records to the cloud (no quota burn) + the local yield."""
    s = _s(request)
    await _record_fail(s, mac,
                       reason=data.get("reason", "QC failed"),
                       test_results=data.get("test_results"),
                       product_type=data.get("product", ""),
                       firmware_ver=data.get("firmware_ver", ""))
    return {"ok": True, "failed": s.stats_failed}


@router.post("/defect")
async def node_defect(request: Request, data: dict = Body(default={})):
    """Mark a reserved/provisioned node 'defected' (keeps the row + quota slot for yield/
    RMA tracking). Use when a unit that ALREADY got a UUID is found defective — distinct
    from report-fail (a pre-UUID QC reject with no quota burn)."""
    s = _s(request)
    if not getattr(s, "cloud_client", None):
        return {"ok": False, "error": "Not logged in to Cloud"}
    uuid = data.get("uuid")
    if not uuid:
        return {"ok": False, "error": "uuid required"}
    ok = await s.cloud_client.defect(uuid, reason=data.get("reason", "marked defective"))
    if ok and s.ws:
        s.stats_failed += 1
        s.ws.broadcast("stats", {"provisioned": s.stats_provisioned, "failed": s.stats_failed})
    return {"ok": ok}


# ── Playback Test (LDPS-Probe) ───────────────────────

# Pending capture result tracker
_pending_capture: dict[str, dict] = {}


def handle_capture_result(payload: str) -> None:
    """Called from __init__.py when tb:CAPTURE_RESULT received."""
    pending = _pending_capture.get("active")
    if pending:
        try:
            idx = payload.index("{")
            pending["result"] = json.loads(payload[idx:])
        except (ValueError, json.JSONDecodeError):
            pending["result"] = {"error": "parse_failed", "raw": payload[:200]}
        pending["event"].set()


@router.post("/playback-test/{mac}")
async def playback_test(request: Request, mac: str):
    """Run WS2812 signal capture via LDPS-Probe and analyze results.
    Sends SX:PLAY + TB:CAPTURE, waits for CAPTURE_RESULT, validates."""
    s = _s(request)
    if not s.dongle or not s.dongle.connected:
        return JSONResponse({"error": "Dongle not connected"}, 503)

    from app.config import TEST_PACK_UUID
    # CRC-16/CCITT of the test pack UUID — matches Edge-Node packIdFromUuid (RF v2, ADR-016).
    pack_id = _crc16_ccitt(TEST_PACK_UUID.encode())

    # Setup pending capture
    _cleanup_stale(_pending_capture)
    evt = Event()
    _pending_capture["active"] = {"event": evt, "result": None, "ts": time.time()}

    # Broadcast progress
    if s.ws:
        s.ws.broadcast("playback_test", {"status": "starting", "mac": mac})

    # Send PLAY_AND_CAPTURE (Probe starts capture then sends SX:PLAY)
    s.dongle.send("TB", f"PLAY_AND_CAPTURE,0,{pack_id},100,8000")

    # Wait for result (8s capture + overhead) — threaded wait, don't block the loop.
    if not await asyncio.to_thread(evt.wait, 25):
        _pending_capture.pop("active", None)
        if s.ws:
            s.ws.broadcast("playback_test", {"status": "timeout", "mac": mac})
        return JSONResponse({"error": "Capture timeout"}, 408)

    result = _pending_capture.pop("active", {}).get("result")

    if not result or "error" in result:
        if s.ws:
            s.ws.broadcast("playback_test", {"status": "error", "mac": mac})
        return JSONResponse({"error": "Capture failed", "detail": result}, 500)

    # Analyze results
    channels = result.get("channels", [])
    tests = []
    channels_with_signal = 0

    for ch in channels:
        c = ch.get("ch", "?")
        frames = ch.get("frames", 0)
        timing_ok = ch.get("timing_ok", False)
        fps = ch.get("avg_fps", 0)
        drops = ch.get("dropped", 0)

        has_signal = frames > 0
        ch_pass = has_signal and timing_ok and fps > 5
        if has_signal:
            channels_with_signal += 1

        tests.append({
            "channel": c,
            "frames": frames,
            "fps": round(fps, 1),
            "timing_ok": timing_ok,
            "drops": drops,
            "pass": ch_pass,
        })

    # Pass if all channels WITH signal pass (channels without wires are ignored)
    active_channels = [t for t in tests if t["frames"] > 0]
    all_active_pass = all(t["pass"] for t in active_channels) if active_channels else False

    # Stop playback
    s.dongle.send("SX", "STOP")

    status = "pass" if all_active_pass else "fail"
    if s.ws:
        s.ws.broadcast("playback_test", {"status": status, "mac": mac, "tests": tests})

    return {
        "ok": True,
        "pass": all_active_pass,
        "channels_with_signal": channels_with_signal,
        "tests": tests,
    }


def _crc16_ccitt(data: bytes) -> int:
    # MUST match Edge-Node packIdFromUuid (system_context.h): CRC-16/CCITT-FALSE
    # (init 0xFFFF, poly 0x1021, MSB-first) over the UUID string bytes; 0 -> 1 (0 is
    # reserved for "no pack"). The node filters RF frames on this pack_id (ADR-016 v2);
    # the old CRC-8 made the node reject the Probe's test frames so playback QC couldn't pass.
    crc = 0xFFFF
    for byte in data:
        crc ^= (byte << 8)
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if (crc & 0x8000) else (crc << 1)
            crc &= 0xFFFF
    return crc or 1


# ── USB-authoritative node ops (P1/P2/P3 fixes) ──────────────────────────────

@router.post("/read-node")
async def read_node(request: Request, data: dict = Body(...)):
    """Identify the node over USB (read 'i'). USB is in-hand and authoritative, so this
    lets the wizard pick a node by its REAL MAC + see its current identity WITHOUT relying
    on RF discover (which can return a different node, or miss it when the node's ESP-NOW
    channel ≠ the dongle's). Body: {port}."""
    from app.node_serial import read_identity
    port = (data or {}).get("port")
    if not port:
        return JSONResponse({"error": "port required"}, 400)
    try:
        ident = await asyncio.to_thread(read_identity, port)
    except Exception as e:
        return JSONResponse({"error": f"USB read error on {port}: {e}"}, 500)
    if not ident.get("mac"):
        return JSONResponse({"error": f"No node responding on {port} — check the cable/port."}, 409)
    return {"ok": True, "mac": ident["mac"].upper(), "uuid": ident.get("uuid") or "",
            "fw": ident.get("fw") or "", "key_id": ident.get("key_id") or "",
            "provisioned": bool(ident.get("uuid"))}


@router.post("/clear")
async def clear_node(request: Request, data: dict = Body(...)):
    """Un-provision the node over USB ('U') so it can be RE-provisioned WITHOUT a reflash
    (identity is write-once; re-mint needs a blank node). Clears uuid + genuineness + owner
    from NVS only — the SD (packs/logs) is untouched. Body: {port}."""
    from app.node_serial import clear_identity
    port = (data or {}).get("port")
    if not port:
        return JSONResponse({"error": "port required"}, 400)
    try:
        r = await asyncio.to_thread(clear_identity, port)
    except Exception as e:
        return JSONResponse({"error": f"USB clear error on {port}: {e}"}, 500)
    if not r.get("ok"):
        return JSONResponse({"error": r.get("detail", "clear failed")}, 500)
    return {"ok": True, "detail": r["detail"]}


@router.post("/detect-node")
async def detect_node(request: Request):
    """Auto-detect the Node's USB port so the operator doesn't have to guess which
    /dev/cu.* is which. Probes each candidate serial port with 'i': an Edge-Node answers
    with a 'MAC=' line, whereas the dongle just streams sx:/en: (no MAC=). Skips the port
    of an already-connected dongle (probing resets the ESP32-S3 → would drop its RF link).
    Returns {ok, nodes:[{port, mac, uuid, fw, provisioned}]}."""
    from app.node_serial import read_identity
    from app.utils import list_serial_ports
    s = _s(request)
    dongle_port = getattr(getattr(s, "dongle", None), "port", None) if getattr(getattr(s, "dongle", None), "connected", False) else None
    cand = [p["device"] for p in list_serial_ports()
            if any(k in p["device"] for k in ("usbmodem", "ttyACM", "ttyUSB", "wchusbserial", "SLAB"))
            and p["device"] != dongle_port]
    found = []
    for port in cand:
        try:
            ident = await asyncio.to_thread(read_identity, port)
        except Exception:
            continue
        if ident.get("mac"):
            found.append({"port": port, "mac": ident["mac"].upper(),
                          "uuid": ident.get("uuid") or "", "fw": ident.get("fw") or "",
                          "provisioned": bool(ident.get("uuid"))})
    return {"ok": True, "nodes": found, "probed": cand}
