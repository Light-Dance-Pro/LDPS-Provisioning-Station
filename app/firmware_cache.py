"""Firmware / program cache — the Station is the factory's cloud-facing gateway.

Node firmware and the Hub program retain the legacy product lookup during their
separate release-authority migration. Console Hub Dongle factory images use the
manufacturer-authenticated canonical release endpoint and a complete target/write
contract. Cached Dongle bytes are reused only after the authority still assigns the
same immutable artifact and the local size and hash are re-verified.

Returns dicts with: ok, version, path, changed, plus error/offline/note on edge cases.
"""
from __future__ import annotations

import hashlib
import json
import os

import httpx

from app.config import STATIC_DIR

CACHE_DIR = os.path.join(STATIC_DIR, "firmware_cache")


def _slug(s: str) -> str:
    return "".join(c if (c.isalnum() or c in "._-") else "-" for c in (s or "_"))


def _read_manifest(man_path: str) -> dict:
    if os.path.exists(man_path):
        try:
            with open(man_path) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def cached_version(product: str, channel: str = "stable") -> str | None:
    """The version currently in the local cache for this product/channel, or None."""
    man = _read_manifest(os.path.join(CACHE_DIR, _slug(product), _slug(channel), "manifest.json"))
    p = man.get("path")
    return man.get("version") if (p and os.path.exists(p)) else None


async def get_latest(cloud_url: str, product: str, channel: str = "stable",
                     timeout: float = 15.0) -> dict:
    """Ensure the latest published build for `product`/`channel` is in the local cache.

    Cheap version check first; downloads + sha256-verifies only on a version change.
    On a network failure, falls back to the cached copy if present.
    """
    pdir = os.path.join(CACHE_DIR, _slug(product), _slug(channel))
    os.makedirs(pdir, exist_ok=True)
    man_path = os.path.join(pdir, "manifest.json")
    cached = _read_manifest(man_path)
    cached_ok = bool(cached.get("path") and os.path.exists(cached.get("path", "")))

    # 1. cheap version check
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(f"{cloud_url}/firmware/latest",
                                  params={"product": product, "channel": channel})
        d = r.json() if r.status_code == 200 else {}
    except Exception as e:
        if cached_ok:
            return {"ok": True, "version": cached.get("version"), "path": cached["path"],
                    "changed": False, "offline": True}
        return {"ok": False, "error": f"version check failed: {e}"}

    latest = d.get("version")
    if not latest:
        if cached_ok:
            return {"ok": True, "version": cached.get("version"), "path": cached["path"],
                    "changed": False, "note": "no published release — using cache"}
        return {"ok": False, "error": f"no published firmware for {product} ({channel})"}

    # 2. already the latest → no download (don't interrupt the line)
    if cached.get("version") == latest and cached_ok:
        return {"ok": True, "version": latest, "path": cached["path"], "changed": False}

    # 3. new version → download once + verify sha256
    dl = d.get("download_url")
    if not dl:
        return {"ok": False, "error": "latest release has no download_url"}
    vdir = os.path.join(pdir, _slug(latest))
    os.makedirs(vdir, exist_ok=True)
    fpath = os.path.join(vdir, "firmware.bin")
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.get(dl)
            resp.raise_for_status()
            content = resp.content
        with open(fpath, "wb") as f:
            f.write(content)
    except Exception as e:
        return {"ok": False, "error": f"download failed: {e}"}

    sha = d.get("sha256")
    if sha:
        got = hashlib.sha256(content).hexdigest()
        if got.lower() != str(sha).lower():
            try:
                os.remove(fpath)
            except OSError:
                pass
            return {"ok": False, "error": f"sha256 mismatch (got {got[:12]}…, want {str(sha)[:12]}…)"}

    with open(man_path, "w") as f:
        json.dump({"product": product, "channel": channel, "version": latest,
                   "sha256": sha, "path": fpath}, f)
    return {"ok": True, "version": latest, "path": fpath, "changed": True}


_FACTORY_CONTRACTS = {
    "console-dongle": {
        "target": "console-hub-dongle-esp32s3-v1",
        "profile": "esp32s3-console-dongle-v1",
    },
}


def _normalize_factory_release(payload: object, device: str) -> tuple[dict | None, str | None]:
    contract = _FACTORY_CONTRACTS.get(device)
    if not contract or not isinstance(payload, dict) or payload.get("ok") is not True:
        reason = payload.get("reason") if isinstance(payload, dict) else None
        return None, str(reason or "release authority rejected the request")
    target, release, artifact = (
        payload.get("target"), payload.get("release"), payload.get("artifact")
    )
    if not all(isinstance(part, dict) for part in (target, release, artifact)):
        return None, "incomplete release authority response"
    if (target.get("key") != contract["target"]
            or target.get("target_kind") != "mcu_firmware"
            or target.get("hardware_profile") != contract["profile"]):
        return None, "factory firmware target contract mismatch"
    if (artifact.get("purpose") != "factory"
            or artifact.get("artifact_kind") != "esp32_factory"
            or artifact.get("flash_offset") != 0):
        return None, "factory firmware write contract mismatch"
    version = str(release.get("version") or "").strip()
    release_id = str(release.get("id") or "").strip()
    artifact_id = str(artifact.get("id") or "").strip()
    download_url = str(artifact.get("download_url") or "").strip()
    sha256 = str(artifact.get("sha256") or "").strip().lower()
    try:
        file_size = int(artifact.get("file_size") or 0)
        revision = int(target.get("revision") or 0)
    except (TypeError, ValueError):
        return None, "invalid factory firmware metadata"
    if (not version or not release_id or not artifact_id or not download_url
            or len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256)
            or file_size < 1024 or revision < 1):
        return None, "invalid factory firmware metadata"
    return {
        "version": version,
        "release_id": release_id,
        "artifact_id": artifact_id,
        "target_revision": revision,
        "download_url": download_url,
        "sha256": sha256,
        "file_size": file_size,
    }, None


def _file_matches(path: str, file_size: int, sha256: str) -> bool:
    if not path or not os.path.isfile(path) or os.path.getsize(path) != file_size:
        return False
    digest = hashlib.sha256()
    with open(path, "rb") as firmware:
        for chunk in iter(lambda: firmware.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest() == sha256


async def get_canonical_factory(cloud_client, device: str, timeout: float = 120.0) -> dict:
    """Resolve, cache and verify one server-selected dongle factory image.

    Authority must answer every write attempt. A stale cache is never used when a
    release is withdrawn, unassigned or unreachable; matching cache content only
    avoids downloading the same immutable artifact again.
    """
    payload = await cloud_client.resolve_factory_firmware(device)
    release, reason = _normalize_factory_release(payload, device)
    if not release:
        detail = payload.get("error") if isinstance(payload, dict) else None
        return {"ok": False, "error": reason or detail or "release unavailable"}

    pdir = os.path.join(CACHE_DIR, _slug(device), "factory")
    os.makedirs(pdir, exist_ok=True)
    man_path = os.path.join(pdir, "manifest.json")
    cached = _read_manifest(man_path)
    identity = (release["release_id"], release["artifact_id"], release["target_revision"])
    cached_identity = (
        cached.get("release_id"), cached.get("artifact_id"), cached.get("target_revision")
    )
    if cached_identity == identity and _file_matches(
        str(cached.get("path") or ""), release["file_size"], release["sha256"]
    ):
        return {"ok": True, **release, "path": cached["path"], "changed": False}

    fpath = os.path.join(pdir, f"{_slug(release['artifact_id'])}.factory.bin")
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(release["download_url"])
            response.raise_for_status()
            content = response.content
    except Exception as exc:
        return {"ok": False, "error": f"factory firmware download failed: {exc}"}
    if len(content) != release["file_size"]:
        return {"ok": False, "error": "factory firmware size mismatch"}
    if hashlib.sha256(content).hexdigest() != release["sha256"]:
        return {"ok": False, "error": "factory firmware sha256 mismatch"}
    staged_path = f"{fpath}.part"
    with open(staged_path, "wb") as firmware:
        firmware.write(content)
        firmware.flush()
        os.fsync(firmware.fileno())
    os.replace(staged_path, fpath)
    staged_manifest = f"{man_path}.part"
    with open(staged_manifest, "w") as manifest:
        json.dump({**release, "path": fpath}, manifest)
        manifest.flush()
        os.fsync(manifest.fileno())
    os.replace(staged_manifest, man_path)
    return {"ok": True, **release, "path": fpath, "changed": True}
