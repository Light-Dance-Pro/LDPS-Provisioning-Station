import json
import os
import tempfile
import unittest
from pathlib import Path

from app.provision_journal import (
    clear_hub_pending,
    load_hub_pending,
    mark_hub_written,
    save_hub_pending,
)


HUB_UUID = "11111111-2222-4333-8444-555555555555"


def _certificate():
    return {
        "hub_uuid": HUB_UUID,
        "cpuid": "0123456789abcdef",
        "product": "Touch Hub",
        "binding_signature": "ab" * 64,
        "key_id": "prod-v1",
        "signing_keys": [{"key_id": "prod-v1", "public_key": "cd" * 32,
                          "algo": "ed25519"}],
        "authority_stage": "local",
    }


class ProvisionJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "pending.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_round_trip_is_private_and_transitions_to_written(self):
        signed = save_hub_pending(_certificate(), path=self.path)
        self.assertEqual(signed["phase"], "signed")
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)
        self.assertEqual(load_hub_pending(self.path)["hub_uuid"], HUB_UUID)

        written = mark_hub_written(HUB_UUID, path=self.path)
        self.assertEqual(written["phase"], "written")
        self.assertEqual(load_hub_pending(self.path)["phase"], "written")

    def test_clear_requires_exact_expected_uuid(self):
        save_hub_pending(_certificate(), path=self.path)
        self.assertFalse(clear_hub_pending("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee", self.path))
        self.assertIsNotNone(load_hub_pending(self.path))
        self.assertTrue(clear_hub_pending(HUB_UUID, self.path))
        self.assertIsNone(load_hub_pending(self.path))

    def test_malformed_or_secret_bearing_shape_fails_closed(self):
        self.path.write_text(json.dumps({"schema": 1, "phase": "signed", "hub_uuid": HUB_UUID,
                                         "recovery_key": "must-not-be-used"}), encoding="utf-8")
        self.assertIsNone(load_hub_pending(self.path))
        with self.assertRaises(ValueError):
            save_hub_pending({**_certificate(), "signing_keys": {}}, path=self.path)

    def test_journal_keeps_only_approved_public_fields(self):
        record = save_hub_pending({**_certificate(), "manufacturer_api_key": "secret",
                                   "recovery_key": "secret"}, path=self.path)
        self.assertNotIn("manufacturer_api_key", record)
        self.assertNotIn("recovery_key", record)
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertNotIn("manufacturer_api_key", raw)
        self.assertNotIn("recovery_key", raw)


if __name__ == "__main__":
    unittest.main()
