"""Crash-durable public journal for one in-flight Hub provisioning transaction.

The journal deliberately contains only the Hub's public certificate tuple and
workflow phase. Manufacturer credentials and recovery secrets never belong here.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from app.config import HUB_PROVISION_JOURNAL_PATH, LDPS_STAGE_RESOLVED

_LOCK = threading.RLock()
_SCHEMA = 1
_PHASES = {"signed", "written"}
_PUBLIC_FIELDS = (
    "hub_uuid",
    "cpuid",
    "product",
    "binding_signature",
    "key_id",
    "signing_keys",
    "authority_stage",
)


def _path(path: str | os.PathLike[str] | None = None) -> Path:
    return Path(path or HUB_PROVISION_JOURNAL_PATH)


def _validated(raw: object) -> dict | None:
    if not isinstance(raw, dict) or raw.get("schema") != _SCHEMA:
        return None
    if raw.get("phase") not in _PHASES:
        return None
    required = ("hub_uuid", "cpuid", "product", "binding_signature", "key_id",
                "authority_stage")
    if any(not isinstance(raw.get(key), str) or not raw[key].strip() for key in required):
        return None
    try:
        if str(UUID(raw["hub_uuid"])) != raw["hub_uuid"].lower():
            return None
    except (ValueError, AttributeError):
        return None
    if not re.fullmatch(r"[0-9a-fA-F]{128}", raw["binding_signature"]):
        return None
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", raw["key_id"]):
        return None
    signing_keys = raw.get("signing_keys")
    if not isinstance(signing_keys, list) or not signing_keys:
        return None
    if any(
        not isinstance(item, dict)
        or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", str(item.get("key_id", "")))
        or item.get("algo") != "ed25519"
        or not re.fullmatch(r"[0-9a-fA-F]{64}", str(item.get("public_key", "")))
        for item in signing_keys
    ):
        return None
    if not any(item.get("key_id") == raw["key_id"] for item in signing_keys):
        return None
    if raw["authority_stage"] not in {"local", "prod"}:
        return None
    return {
        "schema": _SCHEMA,
        "phase": raw["phase"],
        **{key: raw.get(key) for key in _PUBLIC_FIELDS},
        "updated_at": raw.get("updated_at") if isinstance(raw.get("updated_at"), str) else "",
    }


def load_hub_pending(path: str | os.PathLike[str] | None = None) -> dict | None:
    target = _path(path)
    with _LOCK:
        try:
            with target.open("r", encoding="utf-8") as handle:
                return _validated(json.load(handle))
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
            return None


def save_hub_pending(
    public_certificate: dict,
    phase: str = "signed",
    path: str | os.PathLike[str] | None = None,
) -> dict:
    record = _validated({
        "schema": _SCHEMA,
        "phase": phase,
        **{key: public_certificate.get(key) for key in _PUBLIC_FIELDS},
        "authority_stage": public_certificate.get("authority_stage") or LDPS_STAGE_RESOLVED,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    if record is None:
        raise ValueError("invalid Hub public certificate journal record")

    target = _path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(record, handle, separators=(",", ":"), sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
            os.chmod(target, 0o600)
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise
    return record


def mark_hub_written(
    expected_uuid: str,
    path: str | os.PathLike[str] | None = None,
) -> dict | None:
    with _LOCK:
        record = load_hub_pending(path)
        if not record or record["hub_uuid"] != expected_uuid:
            return None
        return save_hub_pending(record, phase="written", path=path)


def clear_hub_pending(
    expected_uuid: str,
    path: str | os.PathLike[str] | None = None,
) -> bool:
    target = _path(path)
    with _LOCK:
        record = load_hub_pending(path)
        if not record or record["hub_uuid"] != expected_uuid:
            return False
        try:
            target.unlink()
        except FileNotFoundError:
            return False
        return True
