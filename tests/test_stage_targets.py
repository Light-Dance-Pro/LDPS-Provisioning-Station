import asyncio
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("LDPS_STAGE", "local")

from app.config import DEFAULT_CLOUD_URL, STAGE_CLOUD_URLS
from app.routes.cloud import cloud_login


class StageTargetsTest(unittest.TestCase):
    def test_only_supported_cloud_stages_are_exposed(self):
        self.assertEqual(set(STAGE_CLOUD_URLS), {"local", "uat", "prod"})

    def test_named_stages_use_canonical_cloudflare_api_hosts(self):
        self.assertEqual(
            STAGE_CLOUD_URLS["uat"], "https://api-uat.lightdancepro.com"
        )
        self.assertEqual(STAGE_CLOUD_URLS["prod"], "https://api.lightdancepro.com")

    def test_named_remote_stages_have_no_zeabur_origin(self):
        for stage in ("uat", "prod"):
            self.assertNotIn("zeabur.app", STAGE_CLOUD_URLS[stage])

    def test_login_request_cannot_override_the_managed_cloud_target(self):
        state = SimpleNamespace(ws=None)
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(app_state=state)))
        result = {"ok": True, "name": "Factory"}
        with patch("app.routes.cloud._do_login", new=AsyncMock(return_value=result)) as login:
            response = asyncio.run(cloud_login(
                request,
                {"api_key": "test-key", "cloud_url": "https://drift.example"},
            ))
        self.assertEqual(response, result)
        login.assert_awaited_once_with(state, "test-key")

    def test_ui_badge_knows_the_canonical_production_host(self):
        template = (REPO_ROOT / "templates" / "index.html").read_text()
        self.assertIn(r"/api\.lightdancepro\.com/", template)


if __name__ == "__main__":
    unittest.main()
