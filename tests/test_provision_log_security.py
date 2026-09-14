import sqlite3
import stat
import tempfile
import unittest
from pathlib import Path

from app.provision_log import ProvisionLog


class ProvisionLogSecurityTests(unittest.TestCase):
    def test_new_history_rows_do_not_store_or_return_recovery_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "provision.db"
            log = ProvisionLog(str(path))
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            log.add(
                mac="AA:BB:CC:DD:EE:FF",
                uuid="11111111-2222-4333-8444-555555555555",
                product_type="LED Node",
                firmware_ver="test",
                test_results={"sd": True},
                status="success",
                cloud_confirmed=True,
                manufacturer_id="manufacturer-1",
            )

            with sqlite3.connect(path) as conn:
                stored = conn.execute(
                    "SELECT recovery_key FROM provision_logs"
                ).fetchone()[0]
            self.assertIsNone(stored)

            row = log.list(manufacturer_id="manufacturer-1")[0]
            self.assertNotIn("recovery_key", row)
            log._conn.close()

    def test_legacy_recovery_credentials_are_redacted_from_history_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "provision.db"
            log = ProvisionLog(str(path))
            log._conn.execute(
                """INSERT INTO provision_logs
                   (timestamp, mac, status, recovery_key, manufacturer_id)
                   VALUES (?, ?, ?, ?, ?)""",
                ("2026-08-29T00:00:00Z", "AA:BB:CC:DD:EE:FF", "success",
                 "ABCD-EFGH-JKLM-NPQR", "manufacturer-1"),
            )
            log._conn.commit()

            row = log.list(manufacturer_id="manufacturer-1")[0]
            self.assertNotIn("recovery_key", row)
            log._conn.close()


if __name__ == "__main__":
    unittest.main()
