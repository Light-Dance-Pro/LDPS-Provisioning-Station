import argparse
import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("LDPS_STAGE", "local")

from app.desktop_dongle_serial import (
    identity_message,
    normalize_fingerprint,
    read_identity,
    verify_identity_signature,
    write_identity,
)
from tools import provision_desktop_dongle as provision_cli


class DesktopDongleProvisionTest(unittest.TestCase):
    def test_fingerprint_has_one_canonical_form(self):
        self.assertEqual(normalize_fingerprint("aa:bb:cc:dd:ee:ff"), "AABBCCDDEEFF")
        self.assertEqual(normalize_fingerprint("AA-BB-CC-DD-EE-FF"), "AABBCCDDEEFF")
        self.assertEqual(normalize_fingerprint("invalid"), "")

    def test_signature_verifies_offline_and_has_no_stage(self):
        private_key = Ed25519PrivateKey.generate()
        public_hex = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        ).hex()
        hub_uuid = "11111111-2222-4333-8444-555555555555"
        fingerprint = "AABBCCDDEEFF"
        message = identity_message(hub_uuid, fingerprint)
        signature = private_key.sign(message).hex()
        self.assertNotIn(b"uat", message)
        self.assertNotIn(b"prod", message)
        self.assertTrue(verify_identity_signature(
            hub_uuid,
            fingerprint,
            signature,
            "factory-v1",
            [{"key_id": "factory-v1", "public_key": public_hex, "algo": "ed25519"}],
        ))
        self.assertFalse(verify_identity_signature(
            hub_uuid,
            "000000000000",
            signature,
            "factory-v1",
            [{"key_id": "factory-v1", "public_key": public_hex, "algo": "ed25519"}],
        ))

    @patch("app.desktop_dongle_serial._txn")
    def test_identity_response_parser(self, txn):
        txn.return_value = (
            "noise\n"
            "dg:IDENTITY,provisioned=1,iv=1,"
            "uuid=11111111-2222-4333-8444-555555555555,"
            "fingerprint=AABBCCDDEEFF,kid=factory-v1,sig=" + "ab" * 64 + "\n"
        )
        identity = read_identity("test-port")
        self.assertTrue(identity["ok"])
        self.assertTrue(identity["provisioned"])
        self.assertEqual(identity["hardware_fingerprint"], "AABBCCDDEEFF")

    @patch("app.desktop_dongle_serial.time.sleep")
    @patch("app.desktop_dongle_serial.read_identity")
    @patch("app.desktop_dongle_serial._txn")
    def test_lost_write_ack_is_idempotent_when_exact_readback_matches(self, txn, read, _sleep):
        txn.return_value = ""
        read.return_value = {
            "provisioned": True,
            "identity_version": 1,
            "hub_uuid": "11111111-2222-4333-8444-555555555555",
            "hardware_fingerprint": "AABBCCDDEEFF",
            "key_id": "factory-v1",
            "signature": "ab" * 64,
        }
        result = write_identity("test-port", {
            "hub_uuid": "11111111-2222-4333-8444-555555555555",
            "hardware_fingerprint": "AABBCCDDEEFF",
            "key_id": "factory-v1",
            "identity_signature": "ab" * 64,
        })
        self.assertTrue(result["ok"])

    @patch("app.desktop_dongle_serial.time.sleep")
    @patch("app.desktop_dongle_serial.read_identity")
    @patch("app.desktop_dongle_serial._txn")
    def test_lost_write_ack_releases_when_readback_proves_identity_was_not_written(
        self, txn, read, _sleep
    ):
        txn.return_value = ""
        read.return_value = {
            "ok": True,
            "provisioned": False,
            "identity_version": 0,
            "hub_uuid": "",
            "hardware_fingerprint": "AABBCCDDEEFF",
            "key_id": "",
            "signature": "",
        }
        result = write_identity("test-port", {
            "hub_uuid": "11111111-2222-4333-8444-555555555555",
            "hardware_fingerprint": "AABBCCDDEEFF",
            "key_id": "factory-v1",
            "identity_signature": "ab" * 64,
        })
        self.assertFalse(result["ok"])
        self.assertTrue(result["safe_to_release"])

    @patch("app.desktop_dongle_serial.time.sleep")
    @patch("app.desktop_dongle_serial.read_identity")
    @patch("app.desktop_dongle_serial._txn")
    def test_lost_write_ack_retains_reservation_when_readback_is_unavailable(
        self, txn, read, _sleep
    ):
        txn.return_value = ""
        read.return_value = {
            "ok": False,
            "provisioned": False,
            "error": "no_response",
        }
        result = write_identity("test-port", {
            "hub_uuid": "11111111-2222-4333-8444-555555555555",
            "hardware_fingerprint": "AABBCCDDEEFF",
            "key_id": "factory-v1",
            "identity_signature": "ab" * 64,
        })
        self.assertFalse(result["ok"])
        self.assertFalse(result["safe_to_release"])

    @patch("tools.provision_desktop_dongle.write_identity")
    @patch("tools.provision_desktop_dongle.verify_identity_signature", return_value=False)
    @patch("tools.provision_desktop_dongle.manufacturer_key", return_value="local-test-key")
    @patch("tools.provision_desktop_dongle.read_identity")
    @patch("tools.provision_desktop_dongle.read_status")
    @patch("tools.provision_desktop_dongle.CloudClient")
    def test_invalid_cloud_signature_releases_reservation_before_usb_write(
        self, cloud_cls, read_status, read_identity, _manufacturer_key,
        _verify_signature, write_identity_mock,
    ):
        read_status.return_value = {
            "ok": True,
            "hardware_fingerprint": "AABBCCDDEEFF",
            "sx1262": "ok",
            "espnow": "ok",
            "firmware_ver": "1.2.16",
        }
        read_identity.return_value = {
            "ok": True,
            "provisioned": False,
            "hardware_fingerprint": "AABBCCDDEEFF",
        }
        cloud = Mock()
        cloud.login = AsyncMock(return_value={"ok": True})
        cloud.provision_desktop_dongle = AsyncMock(return_value={
            "ok": True,
            "hub_uuid": "11111111-2222-4333-8444-555555555555",
            "hardware_fingerprint": "AABBCCDDEEFF",
            "identity_signature": "ab" * 64,
            "key_id": "factory-v1",
            "signing_keys": [],
        })
        cloud.confirm_desktop_dongle = AsyncMock(return_value={
            "ok": True,
            "status": 200,
            "error": "",
        })
        cloud_cls.return_value = cloud
        args = argparse.Namespace(
            port="test-port",
            product="Desktop Hub Dongle",
            batch="",
            resume=False,
        )

        with patch("builtins.print"):
            result = asyncio.run(provision_cli.run(args))

        self.assertEqual(result, 4)
        cloud.confirm_desktop_dongle.assert_awaited_once_with(
            "11111111-2222-4333-8444-555555555555", success=False
        )
        write_identity_mock.assert_not_called()

    @patch("tools.provision_desktop_dongle.read_status")
    def test_cli_fails_before_reservation_when_espnow_qc_fails(self, read_status):
        read_status.return_value = {
            "ok": True,
            "hardware_fingerprint": "AABBCCDDEEFF",
            "sx1262": "ok",
            "espnow": "err",
            "firmware_ver": "1.2.12",
        }
        args = argparse.Namespace(
            port="test-port",
            product="Desktop Hub Dongle",
            batch="",
            resume=False,
        )

        with patch("builtins.print"):
            result = asyncio.run(provision_cli.run(args))

        self.assertEqual(result, 2)


if __name__ == "__main__":
    unittest.main()
