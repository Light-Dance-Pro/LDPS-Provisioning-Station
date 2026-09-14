import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.routes.provision_hub import (
    _pending_matches_payload,
    _same_hub_is_proven_fresh,
    _verified_boot_matches,
    hub_confirm,
    hub_provision,
)
from app.routes.provision import finalize


HUB_UUID = "11111111-2222-4333-8444-555555555555"
CPUID = "0123456789abcdef"


class _Response:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


class _Client:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def get(self, _url):
        return self._response


class HubProvisionRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_uat_guard_refuses_node_and_hub_before_hardware_or_cloud(self):
        cloud = SimpleNamespace(api_key="factory", provision_hub=AsyncMock())
        state = SimpleNamespace(cloud_client=cloud, hub_pending=None)
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(app_state=state)))

        with patch("app.routes.provision_hub.IDENTITY_MINTING_ALLOWED", False):
            hub_response = await hub_provision(
                request, {"cpuid": CPUID, "product": "Touch Hub"})
        with patch("app.routes.provision.IDENTITY_MINTING_ALLOWED", False):
            node_response = await finalize(
                request, "14:C1:9F:5B:AF:94", {"port": "/dev/test", "product": "LED Node"})

        self.assertEqual(hub_response.status_code, 403)
        self.assertEqual(node_response.status_code, 403)
        cloud.provision_hub.assert_not_awaited()

    async def test_same_pending_hub_is_resumed_without_remint(self):
        pending = {
            "phase": "signed",
            "hub_uuid": HUB_UUID,
            "cpuid": CPUID,
            "product": "Touch Hub",
            "binding_signature": "ab" * 64,
            "key_id": "local-v1",
            "signing_keys": [{"key_id": "local-v1", "public_key": "cd" * 32,
                              "algo": "ed25519"}],
            "authority_stage": "local",
            "updated_at": "2026-08-29T00:00:00+00:00",
        }
        cloud = SimpleNamespace(api_key="factory", provision_hub=AsyncMock())
        state = SimpleNamespace(cloud_client=cloud, hub_pending=pending)
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(app_state=state)))

        response = await hub_provision(
            request, {"cpuid": CPUID, "product": "Touch Hub"})

        self.assertTrue(response["ok"])
        self.assertTrue(response["resumed"])
        self.assertEqual(response["hub_uuid"], HUB_UUID)
        cloud.provision_hub.assert_not_awaited()

    def test_write_payload_must_match_entire_pending_certificate(self):
        payload = {
            "hub_uuid": HUB_UUID,
            "cpuid": CPUID,
            "binding_signature": "ab" * 64,
            "key_id": "prod-v1",
            "signing_keys": [{"key_id": "prod-v1", "public_key": "cd" * 32,
                              "algo": "ed25519"}],
        }
        self.assertTrue(_pending_matches_payload(dict(payload), payload))
        self.assertFalse(_pending_matches_payload(
            {**payload, "binding_signature": "ef" * 64}, payload))
        self.assertFalse(_pending_matches_payload(None, payload))

    def test_boot_recovery_requires_verified_exact_uuid(self):
        self.assertTrue(_verified_boot_matches(
            {"boot_verified": True, "hub_uuid": HUB_UUID}, HUB_UUID))
        self.assertFalse(_verified_boot_matches(
            {"boot_verified": False, "hub_uuid": HUB_UUID}, HUB_UUID))
        self.assertFalse(_verified_boot_matches(
            {"boot_verified": True, "hub_uuid": "different"}, HUB_UUID))

    async def test_release_requires_same_fresh_cpuid(self):
        with patch(
            "app.routes.provision_hub.httpx.AsyncClient",
            return_value=_Client(_Response(200, {"cpuid": CPUID})),
        ):
            self.assertTrue(await _same_hub_is_proven_fresh(CPUID))
            self.assertFalse(await _same_hub_is_proven_fresh("different"))

    async def test_ambiguous_release_is_refused_before_cloud_delete(self):
        cloud = SimpleNamespace(api_key="factory", confirm_hub=AsyncMock())
        state = SimpleNamespace(
            cloud_client=cloud,
            hub_pending={"hub_uuid": HUB_UUID, "cpuid": CPUID,
                         "authority_stage": "local"},
        )
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(app_state=state)))

        with patch(
            "app.routes.provision_hub._same_hub_is_proven_fresh",
            new=AsyncMock(return_value=False),
        ):
            response = await hub_confirm(
                request, {"hub_uuid": HUB_UUID, "success": False})

        self.assertEqual(response.status_code, 409)
        cloud.confirm_hub.assert_not_awaited()

    async def test_commit_is_refused_before_exact_final_qc(self):
        cloud = SimpleNamespace(api_key="factory", confirm_hub=AsyncMock())
        state = SimpleNamespace(cloud_client=cloud, hub_pending=None)
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(app_state=state)))

        with patch(
            "app.routes.provision_hub._hub_final_qc_passes",
            new=AsyncMock(return_value=False),
        ):
            response = await hub_confirm(
                request, {"hub_uuid": HUB_UUID, "success": True})

        self.assertEqual(response.status_code, 409)
        cloud.confirm_hub.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
