import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("LDPS_STAGE", "local")

from app.config import STAGE_CLOUD_URLS, _derive_stage


class StageTargetsTest(unittest.TestCase):
    def test_named_stages_use_canonical_cloudflare_api_hosts(self):
        self.assertEqual(
            STAGE_CLOUD_URLS["uat"], "https://api-uat.lightdancepro.com"
        )
        self.assertEqual(STAGE_CLOUD_URLS["prod"], "https://api.lightdancepro.com")

    def test_named_remote_stages_have_no_zeabur_origin(self):
        for stage in ("uat", "prod"):
            self.assertNotIn("zeabur.app", STAGE_CLOUD_URLS[stage])

    def test_direct_canonical_urls_derive_the_correct_badge_stage(self):
        self.assertEqual(_derive_stage("https://api-uat.lightdancepro.com"), "uat")
        self.assertEqual(_derive_stage("https://api.lightdancepro.com"), "prod")

    def test_ui_badge_knows_the_canonical_production_host(self):
        template = (REPO_ROOT / "templates" / "index.html").read_text()
        self.assertIn(r"/api\.lightdancepro\.com/", template)


if __name__ == "__main__":
    unittest.main()
