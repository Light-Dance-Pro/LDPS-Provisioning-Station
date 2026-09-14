import unittest
from unittest.mock import patch

from app.node_serial import _classify_uncertain_write


UUID = "11111111-2222-4333-8444-555555555555"
SIG = "ab" * 64
KEY_ID = "v1"
MAC = "AA:BB:CC:DD:EE:FF"


class NodeSerialRecoveryTests(unittest.TestCase):
    @patch("app.node_serial.time.sleep", return_value=None)
    @patch("app.node_serial.read_identity")
    def test_exact_readback_converts_lost_response_to_success(self, read_identity, _sleep):
        read_identity.return_value = {
            "mac": "AA:BB:CC:DD:EE:FF", "uuid": UUID,
            "sig": SIG, "key_id": KEY_ID,
        }
        result = _classify_uncertain_write("/dev/test", MAC, UUID, SIG, KEY_ID, "lost")
        self.assertTrue(result["ok"])
        self.assertFalse(result["safe_to_release"])

    @patch("app.node_serial.time.sleep", return_value=None)
    @patch("app.node_serial.read_identity")
    def test_readable_blank_node_is_safe_to_release(self, read_identity, _sleep):
        read_identity.return_value = {
            "mac": "AA:BB:CC:DD:EE:FF", "uuid": "", "sig": "", "key_id": "",
        }
        result = _classify_uncertain_write("/dev/test", MAC, UUID, SIG, KEY_ID, "lost")
        self.assertFalse(result["ok"])
        self.assertTrue(result["safe_to_release"])
        self.assertFalse(result["ambiguous"])

    @patch("app.node_serial.time.sleep", return_value=None)
    @patch("app.node_serial.read_identity")
    def test_partial_same_uuid_retains_reservation(self, read_identity, _sleep):
        read_identity.return_value = {
            "mac": "AA:BB:CC:DD:EE:FF", "uuid": UUID, "sig": "", "key_id": "",
        }
        result = _classify_uncertain_write("/dev/test", MAC, UUID, SIG, KEY_ID, "lost")
        self.assertFalse(result["ok"])
        self.assertFalse(result["safe_to_release"])
        self.assertTrue(result["ambiguous"])

    @patch("app.node_serial.time.sleep", return_value=None)
    @patch("app.node_serial.read_identity", side_effect=OSError("device disappeared"))
    def test_unreadable_node_retains_reservation(self, _read_identity, _sleep):
        result = _classify_uncertain_write("/dev/test", MAC, UUID, SIG, KEY_ID, "lost")
        self.assertFalse(result["ok"])
        self.assertFalse(result["safe_to_release"])
        self.assertTrue(result["ambiguous"])

    @patch("app.node_serial.time.sleep", return_value=None)
    @patch("app.node_serial.read_identity")
    def test_reused_usb_path_never_proves_safe_release(self, read_identity, _sleep):
        read_identity.return_value = {
            "mac": "11:22:33:44:55:66", "uuid": "", "sig": "", "key_id": "",
        }
        result = _classify_uncertain_write("/dev/test", MAC, UUID, SIG, KEY_ID, "lost")
        self.assertFalse(result["ok"])
        self.assertFalse(result["safe_to_release"])
        self.assertTrue(result["ambiguous"])


if __name__ == "__main__":
    unittest.main()
