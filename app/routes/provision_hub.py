"""Hub provisioning workflow routes (flow B — HUB_IDENTITY_DESIGN §5/§6.1).

Build order (Xavier): cloud comms → GUI → HW. This file is the cloud-orchestration
layer + the GUI's backend. The physical transport to the assembled OPi (read its
RK3566 cpuid, write hub_boot_identity.json + signing_keys.json to its SD, run Hub QC)
is the §6.1 provisioning channel = the step-3 hardware piece; until then the operator
supplies the cpuid and the signed binding is returned for that later write. The cloud
calls here are real (verified against the running cloud)."""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Request, Body
from fastapi.responses import JSONResponse

from app.config import HUB_HOST, IDENTITY_MINTING_ALLOWED, LDPS_STAGE_RESOLVED
from app.provision_journal import (
    clear_hub_pending,
    mark_hub_written,
    save_hub_pending,
)
from app.utils import log

router = APIRouter()


def _s(r: Request):
    return r.app.state.app_state


def _need_cloud(s):
    return getattr(s, "cloud_client", None) and s.cloud_client.api_key


def _public_pending(record: dict | None) -> dict | None:
    if not record:
        return None
    return {key: record.get(key) for key in (
        "phase", "hub_uuid", "cpuid", "product", "binding_signature",
        "key_id", "signing_keys", "authority_stage", "updated_at",
    )}


def _pending_matches_payload(pending: dict | None, payload: dict) -> bool:
    return bool(pending) and all(
        pending.get(key) == payload.get(key)
        for key in ("hub_uuid", "cpuid", "binding_signature", "key_id", "signing_keys")
    )


def _clear_matching_pending(s, hub_uuid: str) -> None:
    pending = getattr(s, "hub_pending", None) or {}
    if pending.get("hub_uuid") != hub_uuid:
        return
    clear_hub_pending(hub_uuid)
    s.hub_pending = None


def _verified_boot_matches(body: dict, hub_uuid: str) -> bool:
    """True only when the Hub proves this exact public identity at boot."""
    return bool(body.get("boot_verified")) and body.get("hub_uuid") == hub_uuid


async def _read_boot_status() -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{HUB_HOST}/api/system/boot-status")
        return response.json() if response.status_code == 200 else None
    except Exception:
        return None


async def _same_hub_is_proven_fresh(expected_cpuid: str) -> bool:
    """Release is safe only when the same physical Hub still has no identity.

    `/api/provision/cpuid` exists only in the FRESH state after the Hub-side
    gate hardening. Matching the original cpuid prevents a swapped device or
    reused LAN address from authorizing deletion of an ambiguous reservation.
    """
    if not expected_cpuid:
        return False
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{HUB_HOST}/api/provision/cpuid")
        if response.status_code != 200:
            return False
        return (response.json() or {}).get("cpuid") == expected_cpuid
    except Exception:
        return False


async def _hub_final_qc_passes(hub_uuid: str) -> bool:
    """Re-prove identity and operating control plane before Cloud commit."""
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            boot_response = await client.get(f"{HUB_HOST}/api/system/boot-status")
            health_response = await client.get(f"{HUB_HOST}/api/healthz")
        if boot_response.status_code != 200 or health_response.status_code != 200:
            return False
        return (_verified_boot_matches(boot_response.json() or {}, hub_uuid)
                and bool((health_response.json() or {}).get("ok")))
    except Exception:
        return False


@router.post("/provision")
async def hub_provision(request: Request, data: dict = Body(...)):
    """Mint + sign a hub binding for an assembled OPi. body: {cpuid, product_type,
    test_results?, firmware_ver?, provision_batch?}. Returns the binding the Station
    writes onto the hub SD (hub_boot_identity.json + signing_keys.json — step-3
    transport). Reserves quota (status=provisioned, pending COMMIT via /confirm)."""
    s = _s(request)
    if not IDENTITY_MINTING_ALLOWED:
        return JSONResponse({
            "error": "UAT is for application QA and stage enrollment; it cannot mint product "
                     "identity. Switch the Provisioning Station to Production factory mode.",
            "code": "IDENTITY_AUTHORITY_DISABLED",
        }, 403)
    if not _need_cloud(s):
        return JSONResponse({"error": "Not logged in to Cloud"}, 401)
    cpuid = (data.get("cpuid") or "").strip()
    product = data.get("product")   # the catalog product key (ADR-0008)
    if not cpuid:
        return JSONResponse({"error": "cpuid required (read from the assembled OPi)"}, 400)
    if not product:
        return JSONResponse({"error": "product required (QC gate)"}, 400)

    existing = getattr(s, "hub_pending", None) or {}
    if existing:
        if existing.get("authority_stage") != LDPS_STAGE_RESOLVED:
            return JSONResponse({
                "error": f"A Hub transaction from {existing.get('authority_stage', '?').upper()} "
                         f"is pending. Switch back to that Station environment and resume it.",
                "code": "HUB_PENDING_WRONG_STAGE",
                "pending": _public_pending(existing),
            }, 409)
        if existing.get("cpuid") == cpuid and existing.get("product") == product:
            return {"ok": True, "resumed": True, **_public_pending(existing)}
        return JSONResponse({
            "error": "Another Hub identity transaction is pending. Resume, release or defect it "
                     "before starting a different physical Hub.",
            "code": "HUB_PENDING_EXISTS",
            "pending": _public_pending(existing),
        }, 409)

    res = await s.cloud_client.provision_hub(
        cpuid, product,
        test_results=data.get("test_results"),
        firmware_ver=data.get("firmware_ver", ""),
        provision_batch=data.get("provision_batch", ""))
    if not res.get("ok"):
        code = res.get("code")
        status = (409 if code == "CPUID_EXISTS"
                  else 403 if code in ("QUOTA_EXHAUSTED", "QUOTA_NOT_FOUND")
                  else 400 if code == "UNKNOWN_PRODUCT_TYPE" else 502)
        return JSONResponse({"error": res.get("error"), "code": code}, status)

    # Persist the public certificate tuple before returning it. A Station restart or
    # browser reload can then resume this exact reservation without re-minting.
    pending = {
        "hub_uuid": res["hub_uuid"],
        "cpuid": res.get("cpuid") or cpuid,
        "product": product,
        "binding_signature": res.get("binding_signature"),
        "key_id": res.get("key_id"),
        "signing_keys": res.get("signing_keys"),
        "authority_stage": LDPS_STAGE_RESOLVED,
    }
    try:
        s.hub_pending = save_hub_pending(pending, phase="signed")
    except (OSError, ValueError) as exc:
        log(f"[HubProvision] signed identity retained in Cloud but local journal failed: {exc}",
            "ERROR")
        return JSONResponse({
            "error": "Cloud retained the Hub identity, but the Station could not save its "
                     "recovery journal. Fix local storage and retry this same Hub; Cloud will "
                     "return the same certificate.",
            "code": "HUB_JOURNAL_WRITE_FAILED",
            "hub_uuid": res["hub_uuid"],
        }, 500)
    if s.ws:
        s.ws.broadcast("hub_provision", {"step": "signed", "hub_uuid": res["hub_uuid"], "cpuid": cpuid})
    log(f"[HubProvision] signed binding: hub_uuid={res['hub_uuid']} cpuid={cpuid[:12]}… key_id={res.get('key_id')}")
    return {"ok": True, **{k: res.get(k) for k in
                           ("hub_uuid", "cpuid", "binding_signature", "key_id", "signing_keys")}}


@router.get("/pending")
async def hub_pending(request: Request):
    """Return the public in-flight Hub certificate so the UI can offer a safe resume."""
    pending = _public_pending(getattr(_s(request), "hub_pending", None))
    return {"ok": True, "pending": pending, "current_stage": LDPS_STAGE_RESOLVED}


@router.post("/confirm")
async def hub_confirm(request: Request, data: dict = Body(...)):
    """COMMIT (SD binding written + QC passed) or RELEASE (write/QC failed → free quota).
    Passes the cloud's status through so the GUI can tell a retryable network failure
    (status 0/5xx) from a terminal one (missing record or wrong lifecycle)."""
    s = _s(request)
    if not _need_cloud(s):
        return JSONResponse({"error": "Not logged in to Cloud"}, 401)
    hub_uuid = data.get("hub_uuid")
    if "success" in data and not isinstance(data.get("success"), bool):
        return JSONResponse({"error": "success must be a boolean"}, 400)
    success = data.get("success", True)
    if not hub_uuid:
        return JSONResponse({"error": "hub_uuid required"}, 400)
    pending = getattr(s, "hub_pending", None) or {}
    if (pending.get("hub_uuid") == hub_uuid
            and pending.get("authority_stage") != LDPS_STAGE_RESOLVED):
        return JSONResponse({
            "error": f"This transaction belongs to {pending.get('authority_stage', '?').upper()}; "
                     "switch the Station back before confirming or releasing it.",
            "code": "HUB_PENDING_WRONG_STAGE",
        }, 409)

    if success:
        if not await _hub_final_qc_passes(hub_uuid):
            return JSONResponse({
                "error": "Cloud commit refused: the exact Hub identity and final operational QC "
                         "are not currently proven.",
                "code": "HUB_QC_NOT_PROVEN",
                "hub_uuid": hub_uuid,
            }, 409)
    else:
        pending = getattr(s, "hub_pending", None) or {}
        expected_cpuid = pending.get("cpuid") if pending.get("hub_uuid") == hub_uuid else ""
        if not await _same_hub_is_proven_fresh(expected_cpuid):
            return JSONResponse({
                "error": "Release refused: the same Hub is not proven FRESH. Its identity write "
                         "may already have landed; reconnect the same unit and resume/inspect it.",
                "code": "HUB_WRITE_AMBIGUOUS",
                "hub_uuid": hub_uuid,
            }, 409)

    c = await s.cloud_client.confirm_hub(hub_uuid, success=success)
    if c["ok"] and success:
        s.stats_provisioned += 1
        _clear_matching_pending(s, hub_uuid)
        if s.ws:
            s.ws.broadcast("stats", {"provisioned": s.stats_provisioned, "failed": s.stats_failed})
            s.ws.broadcast("hub_provision", {"step": "done", "hub_uuid": hub_uuid})
        log(f"[HubProvision] COMMIT hub_uuid={hub_uuid}")
    elif c["ok"]:
        _clear_matching_pending(s, hub_uuid)
        log(f"[HubProvision] RELEASE hub_uuid={hub_uuid} (quota freed)")
    else:
        log(f"[HubProvision] {'COMMIT' if success else 'RELEASE'} failed for {hub_uuid}: "
            f"status={c['status']} {c['error']}", "WARNING")
    return {"ok": c["ok"], "status": c["status"], "error": c["error"] or None,
            "retryable": (not c["ok"]) and c["status"] in (0, 500, 502, 503, 504)}


@router.post("/defect")
async def hub_defect(request: Request, data: dict = Body(...)):
    """Mark a reserved/provisioned hub 'defected' (keeps row + quota for yield tracking)."""
    s = _s(request)
    if not _need_cloud(s):
        return JSONResponse({"error": "Not logged in to Cloud"}, 401)
    hub_uuid = data.get("hub_uuid")
    if not hub_uuid:
        return JSONResponse({"error": "hub_uuid required"}, 400)
    pending = getattr(s, "hub_pending", None) or {}
    if (pending.get("hub_uuid") == hub_uuid
            and pending.get("authority_stage") != LDPS_STAGE_RESOLVED):
        return JSONResponse({
            "error": f"This transaction belongs to {pending.get('authority_stage', '?').upper()}; "
                     "switch the Station back before marking its result.",
            "code": "HUB_PENDING_WRONG_STAGE",
        }, 409)
    ok = await s.cloud_client.defect_hub(hub_uuid, reason=data.get("reason", ""))
    if ok:
        s.stats_failed += 1
        _clear_matching_pending(s, hub_uuid)
        if s.ws:
            s.ws.broadcast("stats", {"provisioned": s.stats_provisioned, "failed": s.stats_failed})
        log(f"[HubProvision] DEFECT hub_uuid={hub_uuid}")
    return {"ok": ok}


@router.post("/rebind")
async def hub_rebind(request: Request, data: dict = Body(...)):
    """RMA board swap: re-sign the binding to a NEW cpuid (same hub_uuid + owner)."""
    s = _s(request)
    if not IDENTITY_MINTING_ALLOWED:
        return JSONResponse({
            "error": "UAT cannot re-sign product identity. Use the Production factory authority.",
            "code": "IDENTITY_AUTHORITY_DISABLED",
        }, 403)
    if not _need_cloud(s):
        return JSONResponse({"error": "Not logged in to Cloud"}, 401)
    hub_uuid = data.get("hub_uuid")
    cpuid = (data.get("cpuid") or "").strip()
    if not hub_uuid or not cpuid:
        return JSONResponse({"error": "hub_uuid and cpuid required"}, 400)

    res = await s.cloud_client.rebind_hub(hub_uuid, cpuid)
    if not res.get("ok"):
        return JSONResponse({"error": res.get("error")}, 502)
    log(f"[HubProvision] REBIND hub_uuid={hub_uuid} → new cpuid={cpuid[:12]}…")
    return {"ok": True, **{k: res.get(k) for k in
                           ("hub_uuid", "cpuid", "binding_signature", "key_id", "signing_keys")}}


# ── §6.1 provisioning channel (Station → assembled OPi) ─────────────────────────
# Step-3 transport. The Station reaches the OPi's open channel (FRESH/locked only) to
# READ its cpuid and WRITE the cloud-signed binding. LAN HTTP now (set HUB_HOST);
# USB-gadget/eth link-local later — same routes, transport-agnostic. The hub verifies
# the binding against its OWN cpuid before writing, so the identity route cannot
# impersonate. The same FRESH channel also carries raw program/firmware and is
# therefore safe only on the intended isolated physical link; reachable LAN use
# remains a manufacturing-UAT blocker. Authority: HUB_IDENTITY_DESIGN §6.1.

@router.get("/host")
async def hub_host_info():
    """The §6.1 channel target the Station will read/write (shown in the GUI)."""
    return {"hub_host": HUB_HOST}


@router.get("/read-cpuid")
async def hub_read_cpuid():
    """Read the assembled OPi's cpuid over the §6.1 channel (auto-fills the GUI field)."""
    url = f"{HUB_HOST}/api/provision/cpuid"
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(url)
    except Exception as e:
        return JSONResponse({"error": f"cannot reach hub at {HUB_HOST} — check it is powered "
                                      f"+ on the provisioning link ({e})"}, 502)
    if r.status_code == 404:
        return JSONResponse({"error": "hub channel closed — it is already provisioned "
                                      "(RMA-clear it to re-provision)"}, 409)
    if r.status_code != 200:
        return JSONResponse({"error": f"hub returned HTTP {r.status_code}", "body": r.text[:200]}, 502)
    cpuid = (r.json() or {}).get("cpuid", "")
    log(f"[HubChannel] read cpuid={cpuid[:12]}… from {HUB_HOST}")
    return {"ok": True, "cpuid": cpuid, "hub_host": HUB_HOST}


@router.post("/write-identity")
async def hub_write_identity(request: Request, data: dict = Body(...)):
    """Write the cloud-signed binding onto the OPi's SD over the §6.1 channel.

    body: {hub_uuid, cpuid, binding_signature, key_id, signing_keys} (the /provision result).
    The hub re-verifies against its own cpuid before persisting; on success it unlocks in
    place and reports provisioned=true (operator then restarts it + /confirm to commit quota).
    """
    payload = {k: data.get(k) for k in
               ("hub_uuid", "cpuid", "binding_signature", "key_id", "signing_keys")}
    if not (payload["hub_uuid"] and payload["cpuid"] and payload["binding_signature"] and payload["key_id"]):
        return JSONResponse({"error": "hub_uuid, cpuid, binding_signature, key_id required "
                                      "(provision/sign the hub first)"}, 400)
    s = _s(request)
    pending = getattr(s, "hub_pending", None) or {}
    if pending.get("authority_stage") != LDPS_STAGE_RESOLVED:
        return JSONResponse({
            "error": f"This transaction belongs to {pending.get('authority_stage', '?').upper()}; "
                     "switch the Station back before writing it.",
            "code": "HUB_PENDING_WRONG_STAGE",
        }, 409)
    if not _pending_matches_payload(getattr(s, "hub_pending", None), payload):
        return JSONResponse({
            "error": "The write does not match the Station's pending Hub certificate. "
                     "Reload the pending transaction or inspect it; do not write a different identity.",
            "code": "HUB_PENDING_MISMATCH",
        }, 409)

    def written_response(body: dict) -> dict | JSONResponse:
        try:
            updated = mark_hub_written(payload["hub_uuid"])
        except OSError as exc:
            log(f"[HubChannel] identity landed but journal phase update failed: {exc}", "ERROR")
            return JSONResponse({
                "error": "The Hub identity is present, but the Station could not persist the "
                         "recovery checkpoint. Fix local storage and Retry; do not re-mint.",
                "code": "HUB_JOURNAL_WRITE_FAILED",
                "hub_uuid": payload["hub_uuid"],
            }, 500)
        if updated is None:
            return JSONResponse({
                "error": "The Hub identity is present, but its pending Station transaction is "
                         "missing. Keep the unit out of production for audited recovery.",
                "code": "HUB_PENDING_MISSING",
                "hub_uuid": payload["hub_uuid"],
            }, 409)
        s.hub_pending = updated
        return {"ok": True, "hub_host": HUB_HOST, **body}

    url = f"{HUB_HOST}/api/provision/identity"
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(url, json=payload)
    except Exception as e:
        boot = await _read_boot_status()
        if boot and _verified_boot_matches(boot, payload["hub_uuid"]):
            log(f"[HubChannel] write response lost but exact boot identity verified: "
                f"hub_uuid={payload['hub_uuid']}")
            return written_response({
                "provisioned": True,
                "hub_uuid": payload["hub_uuid"],
                "recovered": True,
                "note": "write response lost; exact boot identity verified",
            })
        return JSONResponse({
            "error": f"Hub identity write outcome is ambiguous at {HUB_HOST} ({e}). "
                     "The reservation was retained; reconnect this same Hub and Retry.",
            "code": "HUB_WRITE_AMBIGUOUS",
            "hub_uuid": payload["hub_uuid"],
        }, 502)
    try:
        body = r.json()
    except Exception:
        body = {"body": r.text[:200]}
    if r.status_code != 200:
        # A prior attempt may have written successfully and closed the FRESH
        # channel before its HTTP response reached the Station. Public boot
        # status is a stronger proof than the lost channel response.
        boot = await _read_boot_status()
        if boot and _verified_boot_matches(boot, payload["hub_uuid"]):
            log(f"[HubChannel] closed/rejected write recovered by exact boot identity: "
                f"hub_uuid={payload['hub_uuid']}")
            return written_response({
                "provisioned": True,
                "hub_uuid": payload["hub_uuid"],
                "recovered": True,
                "note": "exact boot identity already present",
            })
        # Surface the hub's own reason (cpuid mismatch / bad sig / closed) verbatim.
        status = r.status_code if r.status_code in (400, 404, 409) else 502
        log(f"[HubChannel] write REJECTED by hub ({r.status_code}): {body.get('error')}")
        return JSONResponse({"error": "hub rejected the write", "hub_status": r.status_code, **body}, status)
    log(f"[HubChannel] wrote identity to {HUB_HOST}: hub_uuid={payload['hub_uuid']} → {body.get('provisioned')}")
    return written_response(body)


@router.post("/flash-dongle")
async def hub_flash_dongle(request: Request):
    """Resolve the canonical Console Hub Dongle factory image and push it to the Hub."""
    s = request.app.state.app_state
    if not _need_cloud(s):
        return JSONResponse({"error": "Not logged in to Cloud"}, 401)
    from app.firmware_cache import get_canonical_factory
    fw = await get_canonical_factory(s.cloud_client, "console-dongle")
    if not fw.get("ok"):
        return JSONResponse({"error": f"dongle firmware: {fw.get('error')}"}, 502)
    try:
        with open(fw["path"], "rb") as f:
            data = f.read()
    except Exception as e:
        return JSONResponse({"error": f"cannot read cached firmware: {e}"}, 500)
    url = f"{HUB_HOST}/api/provision/dongle-firmware"
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(url, content=data, headers={"Content-Type": "application/octet-stream"})
    except Exception as e:
        return JSONResponse({"error": f"cannot reach hub at {HUB_HOST} ({e})"}, 502)
    try:
        body = r.json()
    except Exception:
        body = {"body": r.text[:200]}
    if r.status_code != 200:
        return JSONResponse({"error": "hub rejected the dongle flash", "hub_status": r.status_code, **body}, 502)
    log(f"[HubChannel] pushed dongle fw v{fw['version']} ({len(data)} bytes, downloaded={fw['changed']}) → {HUB_HOST}")
    return {"ok": True, "version": fw["version"], "downloaded": fw["changed"], "hub_host": HUB_HOST, **body}


@router.post("/push-program")
async def hub_push_program(request: Request):
    """Fetch the latest hub PROGRAM (Touch Hub) from the registry (version-check → cache) and
    push it to the hub over §6.1; the hub backs up, installs it, restarts, and rolls back if
    unhealthy. The SD carries only OS + deps — the Station delivers the program."""
    s = request.app.state.app_state
    cloud_url = getattr(s, "cloud_url", "") or ""
    if not cloud_url:
        return JSONResponse({"error": "Not logged in to Cloud"}, 401)
    from app.firmware_cache import get_latest
    fw = await get_latest(cloud_url, "Touch Hub")
    if not fw.get("ok"):
        return JSONResponse({"error": f"hub program: {fw.get('error')}"}, 502)
    try:
        with open(fw["path"], "rb") as f:
            data = f.read()
    except Exception as e:
        return JSONResponse({"error": f"cannot read cached program: {e}"}, 500)
    url = f"{HUB_HOST}/api/provision/program"
    try:
        async with httpx.AsyncClient(timeout=40) as c:
            r = await c.post(url, content=data, headers={"Content-Type": "application/gzip"})
    except Exception as e:
        return JSONResponse({"error": f"cannot reach hub at {HUB_HOST} ({e})"}, 502)
    try:
        body = r.json()
    except Exception:
        body = {"body": r.text[:200]}
    if r.status_code != 200:
        return JSONResponse({"error": "hub rejected the program", "hub_status": r.status_code, **body}, 502)
    log(f"[HubChannel] pushed hub program v{fw['version']} ({len(data)} bytes, downloaded={fw['changed']}) → {HUB_HOST}")
    return {"ok": True, "version": fw["version"], "downloaded": fw["changed"], "hub_host": HUB_HOST, **body}


@router.get("/program-status")
async def hub_program_status():
    """Proxy the hub's program-install outcome {run_id, status: installing|ok|rollback|
    rollback_failed|backup_failed|none}. The auto-flow matches run_id against its own
    push — a stale status file (previous attempt / reboot-wiped) is never mistaken for
    this push's result."""
    url = f"{HUB_HOST}/api/provision/program-status"
    try:
        async with httpx.AsyncClient(timeout=6) as c:
            r = await c.get(url)
        return r.json()
    except Exception as e:
        return JSONResponse({"error": f"cannot reach hub at {HUB_HOST} ({e})"}, 502)


@router.get("/dongle-status")
async def hub_dongle_status():
    """Proxy the hub's dongle-flash outcome {run_id, status: flashing|ok|failed|none} —
    before this, an esptool rc≠0 was indistinguishable from success (result only lived
    in /tmp/dongle_flash.log on the hub)."""
    url = f"{HUB_HOST}/api/provision/dongle-status"
    try:
        async with httpx.AsyncClient(timeout=6) as c:
            r = await c.get(url)
        return r.json()
    except Exception as e:
        return JSONResponse({"error": f"cannot reach hub at {HUB_HOST} ({e})"}, 502)


@router.post("/restart")
async def hub_restart():
    """Ask the just-provisioned hub to restart (hub route is valid ONLY in the
    verified-but-control-plane-inert state right after a §6.1 identity write). The
    in-place unlock leaves the hub LOOKING provisioned but RF-dead until a restart —
    the auto-flow's verify phase drives this + checks the hub comes back healthy."""
    url = f"{HUB_HOST}/api/provision/restart"
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.post(url)
        try:
            body = r.json()
        except Exception:
            body = {"body": r.text[:200]}
        if r.status_code != 200:
            return JSONResponse({"error": "hub refused the restart", "hub_status": r.status_code, **body},
                                r.status_code if r.status_code in (404, 409) else 502)
        return {"ok": True, **body}
    except Exception as e:
        return JSONResponse({"error": f"cannot reach hub at {HUB_HOST} ({e})"}, 502)


@router.get("/status")
async def hub_status():
    """Post-restart QC probe: the hub's boot-status + healthz (main loop alive, dongle
    open) so the verify phase can prove the provisioned hub actually OPERATES — not just
    that its identity file verifies."""
    out = {}
    try:
        async with httpx.AsyncClient(timeout=6) as c:
            b = await c.get(f"{HUB_HOST}/api/system/boot-status")
            out["boot"] = b.json()
            try:
                h = await c.get(f"{HUB_HOST}/api/healthz")
                out["health"] = h.json() if h.status_code == 200 else {"ok": False, "http": h.status_code}
            except Exception as he:
                out["health"] = {"ok": False, "error": str(he)}
        return {"ok": True, **out}
    except Exception as e:
        return JSONResponse({"error": f"cannot reach hub at {HUB_HOST} ({e})"}, 502)
