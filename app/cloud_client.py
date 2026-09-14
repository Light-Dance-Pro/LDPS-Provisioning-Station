"""Cloud API client for provisioning operations.

Uses manufacturer API key authentication (X-Manufacturer-Key header).
Completely separate from Supabase Auth — manufacturers cannot access Studio.
"""
from __future__ import annotations

import httpx
from app.utils import log


class CloudClient:
    def __init__(self, cloud_url: str):
        self.cloud_url = cloud_url.rstrip("/")
        self.api_key: str = ""
        self.manufacturer_id: str = ""
        self.manufacturer_name: str = ""
        self.quotas: list = []

    def _headers(self) -> dict:
        return {"X-Manufacturer-Key": self.api_key} if self.api_key else {}

    async def login(self, api_key: str) -> dict:
        """Authenticate with manufacturer API key."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(f"{self.cloud_url}/provision/login",
                                      json={"api_key": api_key})
            if r.status_code == 200:
                data = r.json()
                if data.get("ok"):
                    self.api_key = api_key
                    self.manufacturer_id = data.get("manufacturer_id", "")
                    self.manufacturer_name = data.get("name", "")
                    self.quotas = data.get("quotas", [])
                    return {
                        "ok": True,
                        "name": self.manufacturer_name,
                        "manufacturer_id": self.manufacturer_id,
                        "quotas": self.quotas,
                    }
            err = "Invalid API key"
            try:
                err = r.json().get("error", err)
            except Exception:
                pass
            return {"ok": False, "error": err}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def get_quota(self) -> list:
        """Re-fetch quotas from login endpoint."""
        if not self.api_key:
            return []
        result = await self.login(self.api_key)
        return result.get("quotas", self.quotas)

    async def resolve_factory_firmware(self, device: str) -> dict:
        """Resolve an allowlisted dongle factory image through release authority."""
        if device != "console-dongle":
            return {"ok": False, "error": "unknown factory firmware device"}
        if not self.api_key:
            return {"ok": False, "error": "manufacturer login required", "status": 401}
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    f"{self.cloud_url}/provision/firmware/{device}",
                    headers=self._headers(),
                )
            try:
                payload = response.json()
            except Exception:
                payload = {}
            if response.status_code == 200 and payload.get("ok") is True:
                return payload
            return {
                "ok": False,
                "status": response.status_code,
                "reason": payload.get("reason"),
                "error": payload.get("error") or payload.get("reason")
                         or f"HTTP {response.status_code}",
            }
        except Exception as exc:
            return {"ok": False, "status": 0, "error": str(exc)}

    async def request_uuid(self, hardware_serial: str, product: str,
                           test_results: dict = None, firmware_ver: str = "") -> dict | None:
        """Mint a node UUID. product (the catalog product key) is REQUIRED (cloud QC gate). Returns
        {uuid, signature, key_id, recovery_key} — signature is the cloud's Ed25519
        genuineness sig over the UUID, written to the node over USB and verified by
        Hubs; recovery_key is the per-node re-claim key (plaintext only in the active
        factory response; idempotent retries return the same key) that the operator
        prints on the box (§3.4) — never written to the node and stored encrypted in
        Cloud. Returns None on failure. Genuineness signing is mandatory: the
        Cloud must not reserve a production identity without signature + key_id."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(f"{self.cloud_url}/provision/request-uuid",
                                      json={
                                          "hardware_serial": hardware_serial,
                                          "product": product,
                                          "test_results": test_results,
                                          "firmware_ver": firmware_ver,
                                      },
                                      headers=self._headers())
            if r.status_code == 200:
                d = r.json()
                return {"uuid": d.get("uuid"),
                        "signature": d.get("signature"),
                        "key_id": d.get("key_id"),
                        "recovery_key": d.get("recovery_key")}
            log(f"[Cloud] request-uuid failed: {r.status_code} {r.text}", "WARNING")
            return None
        except Exception as e:
            log(f"[Cloud] request-uuid error: {e}", "ERROR")
            return None

    async def confirm(self, uuid: str, success: bool = True) -> dict:
        """COMMIT (identity written) or RELEASE (write failed → free quota).
        Returns {ok, status, error} — status 0 = network error (retryable);
        4xx = terminal (e.g. 404 missing record, 409 wrong lifecycle)."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(f"{self.cloud_url}/provision/confirm",
                                      json={"uuid": uuid, "success": success},
                                      headers=self._headers())
            err = ""
            if r.status_code != 200:
                try:
                    err = r.json().get("error", "")
                except Exception:
                    err = r.text[:200]
            return {"ok": r.status_code == 200, "status": r.status_code, "error": err}
        except Exception as e:
            return {"ok": False, "status": 0, "error": str(e)}

    async def defect(self, uuid: str, reason: str = "") -> bool:
        """Mark a reserved/provisioned node 'defected' (keeps row + quota for yield tracking)."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(f"{self.cloud_url}/provision/node/defect",
                                      json={"uuid": uuid, "reason": reason or None},
                                      headers=self._headers())
            return r.status_code == 200
        except Exception:
            return False

    async def report_test_fail(self, hardware_serial: str,
                               test_results: dict = None, reason: str = "") -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(f"{self.cloud_url}/provision/test-fail",
                                      json={
                                          "hardware_serial": hardware_serial,
                                          "test_results": test_results,
                                          "reason": reason,
                                      },
                                      headers=self._headers())
            return r.status_code == 200
        except Exception:
            return False

    # ── Hub provisioning (flow B, §5/§6.1) — the Station reads the assembled OPi's
    #    RK3566 cpuid and the cloud signs the (hub_uuid:cpuid) binding to THAT chip.
    #    The binding_signature + signing_keys are written to the Hub's SD via the Hub
    #    provisioning channel (the "发去hub" step, later); the cloud keeps only key_id.

    async def provision_hub(self, cpuid: str, product: str,
                            test_results: dict = None, firmware_ver: str = "",
                            provision_batch: str = "") -> dict:
        """Reserve + sign a hub binding. Returns the cloud response dict:
        success → {ok: True, hub_uuid, cpuid, binding_signature, key_id, signing_keys};
        failure → {ok: False, error, code?}  (codes: UNKNOWN_PRODUCT_TYPE,
        QUOTA_EXHAUSTED, QUOTA_NOT_FOUND, CPUID_EXISTS). product (the catalog product key)
        must be an active hub-flow product."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(f"{self.cloud_url}/provision/hub",
                                      json={
                                          "cpuid": cpuid,
                                          "product": product,
                                          "test_results": test_results,
                                          "firmware_ver": firmware_ver or None,
                                          "provision_batch": provision_batch or None,
                                      },
                                      headers=self._headers())
            try:
                d = r.json()
            except Exception:
                d = {}
            if r.status_code == 200 and d.get("ok"):
                return d
            log(f"[Cloud] provision-hub failed: {r.status_code} {d}", "WARNING")
            return {"ok": False, "error": d.get("error", f"HTTP {r.status_code}"),
                    "code": d.get("code")}
        except Exception as e:
            log(f"[Cloud] provision-hub error: {e}", "ERROR")
            return {"ok": False, "error": str(e)}

    async def confirm_hub(self, hub_uuid: str, success: bool = True) -> dict:
        """COMMIT (SD binding written) or RELEASE (write failed → frees the quota).
        Returns {ok, status, error} — status 0 = network error (retryable);
        4xx = terminal (404 missing record, 409 wrong lifecycle)."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(f"{self.cloud_url}/provision/hub/confirm",
                                      json={"hub_uuid": hub_uuid, "success": success},
                                      headers=self._headers())
            err = ""
            if r.status_code != 200:
                try:
                    err = r.json().get("error", "")
                except Exception:
                    err = r.text[:200]
            return {"ok": r.status_code == 200, "status": r.status_code, "error": err}
        except Exception as e:
            return {"ok": False, "status": 0, "error": str(e)}

    async def get_signing_keys(self) -> list:
        """Fetch public factory keys; these are safe to cache and use offline."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(f"{self.cloud_url}/provision/signing-keys")
            if r.status_code != 200:
                return []
            return (r.json() or {}).get("keys", [])
        except Exception:
            return []

    async def defect_hub(self, hub_uuid: str, reason: str = "") -> bool:
        """Mark a reserved/provisioned hub 'defected' (keeps row + quota for yield tracking)."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(f"{self.cloud_url}/provision/hub/defect",
                                      json={"hub_uuid": hub_uuid, "reason": reason or None},
                                      headers=self._headers())
            return r.status_code == 200
        except Exception:
            return False

    async def rebind_hub(self, hub_uuid: str, cpuid: str) -> dict:
        """RMA board swap: re-sign (hub_uuid:new_cpuid), same hub_uuid + owner.
        Returns {ok, hub_uuid, cpuid, binding_signature, key_id, signing_keys} or
        {ok: False, error}."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(f"{self.cloud_url}/provision/hub/rebind",
                                      json={"hub_uuid": hub_uuid, "cpuid": cpuid},
                                      headers=self._headers())
            try:
                d = r.json()
            except Exception:
                d = {}
            if r.status_code == 200 and d.get("ok"):
                return d
            log(f"[Cloud] rebind-hub failed: {r.status_code} {d}", "WARNING")
            return {"ok": False, "error": d.get("error", f"HTTP {r.status_code}")}
        except Exception as e:
            return {"ok": False, "error": str(e)}
