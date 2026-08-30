import asyncio
import hashlib
import os
import tempfile
import unittest
from unittest.mock import patch

from app import firmware_cache
from app.cloud_client import CloudClient


def authority_payload(content: bytes = b"x" * 2048) -> dict:
    return {
        "ok": True,
        "target": {
            "key": "console-hub-dongle-esp32s3-v1",
            "target_kind": "mcu_firmware",
            "hardware_profile": "esp32s3-console-dongle-v1",
            "revision": 2,
        },
        "release": {"id": "release-1", "version": "1.2.13"},
        "artifact": {
            "id": "artifact-1",
            "purpose": "factory",
            "artifact_kind": "esp32_factory",
            "flash_offset": 0,
            "download_url": "https://download.test/factory.bin",
            "sha256": hashlib.sha256(content).hexdigest(),
            "file_size": len(content),
        },
    }


class CanonicalFactoryFirmwareTests(unittest.TestCase):
    def test_rejects_each_write_contract_drift(self):
        cases = [
            ("target", "key", "desktop-hub-dongle-esp32s3-v1"),
            ("target", "target_kind", "host_software"),
            ("target", "hardware_profile", "wrong-profile"),
            ("artifact", "purpose", "field_update"),
            ("artifact", "artifact_kind", "esp32_app"),
            ("artifact", "flash_offset", 0x10000),
        ]
        for section, field, value in cases:
            with self.subTest(field=field):
                payload = authority_payload()
                payload[section][field] = value
                release, reason = firmware_cache._normalize_factory_release(
                    payload, "console-dongle"
                )
                self.assertIsNone(release)
                self.assertTrue(reason)

    def test_authority_failure_never_uses_stale_cache(self):
        class FailedClient:
            async def resolve_factory_firmware(self, _device):
                return {"ok": False, "reason": "no_release_assigned"}

        with tempfile.TemporaryDirectory() as cache_dir, patch.object(
            firmware_cache, "CACHE_DIR", cache_dir
        ):
            result = asyncio.run(
                firmware_cache.get_canonical_factory(FailedClient(), "console-dongle")
            )
        self.assertFalse(result["ok"])
        self.assertIn("no_release_assigned", result["error"])

    def test_cloud_client_uses_authenticated_allowlisted_route(self):
        calls = []

        class Response:
            status_code = 200

            @staticmethod
            def json():
                return authority_payload()

        class Client:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def get(self, url, **kwargs):
                calls.append((url, kwargs))
                return Response()

        cloud = CloudClient("https://api.test")
        cloud.api_key = "manufacturer-key"
        with patch("app.cloud_client.httpx.AsyncClient", Client):
            result = asyncio.run(cloud.resolve_factory_firmware("console-dongle"))
        self.assertTrue(result["ok"])
        self.assertEqual(calls, [(
            "https://api.test/provision/firmware/console-dongle",
            {"headers": {"X-Manufacturer-Key": "manufacturer-key"}},
        )])

    def test_download_is_size_and_hash_verified_then_reused(self):
        content = b"z" * 2048

        class AuthorityClient:
            async def resolve_factory_firmware(self, _device):
                return authority_payload(content)

        class DownloadResponse:
            status_code = 200

            def __init__(self, body):
                self.content = body

            @staticmethod
            def raise_for_status():
                return None

        class DownloadClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def get(self, _url):
                return DownloadResponse(content)

        with tempfile.TemporaryDirectory() as cache_dir, patch.object(
            firmware_cache, "CACHE_DIR", cache_dir
        ), patch("app.firmware_cache.httpx.AsyncClient", DownloadClient):
            first = asyncio.run(
                firmware_cache.get_canonical_factory(AuthorityClient(), "console-dongle")
            )
            second = asyncio.run(
                firmware_cache.get_canonical_factory(AuthorityClient(), "console-dongle")
            )
            self.assertTrue(os.path.exists(first["path"]))
        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])


if __name__ == "__main__":
    unittest.main()
