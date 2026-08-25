"""Station configuration constants."""
import os

PORT = int(os.environ.get("PORT", "9000"))
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
TEST_PACK_DIR = os.path.join(STATIC_DIR, "test_pack")
FIRMWARE_DIR = os.path.join(STATIC_DIR, "firmware")
DB_PATH = os.path.join(STATIC_DIR, "provision_log.db")

# Cloud target. LDPS_STAGE selects one of exactly three managed profiles and is
# required, so the Station never silently provisions against Production. UAT and
# Production are immutable canonical targets; only Local may override its workstation
# address. Detail: ../docs/how-to/STAGE_SWITCH.md.
# Station uses manufacturer-key auth only, so no Supabase config here (unlike the Hub).
STAGE_CLOUD_URLS = {
    "local": "http://localhost:3737",
    "uat": "https://api-uat.lightdancepro.com",
    "prod": "https://api.lightdancepro.com",
}
_STAGE = os.environ.get("LDPS_STAGE", "").strip().lower()
if _STAGE not in STAGE_CLOUD_URLS:
    # Fail-fast (Xavier): the Station must NEVER silently default to production. Provisioning
    # against the live cloud burns real quota + writes real recovery keys, so a forgotten stage
    # should STOP startup, not quietly hit prod. To use prod you must say so explicitly.
    raise RuntimeError(
        "LDPS_STAGE is required — the Station refuses to default to production.\n"
        "Set one explicitly, e.g.  LDPS_STAGE=local PORT=9000 python3 main.py  (or =uat / =prod).\n"
        "Stages: " + ", ".join(STAGE_CLOUD_URLS) + ".  See ../docs/how-to/STAGE_SWITCH.md."
    )

DEFAULT_CLOUD_URL = (
    os.environ.get("LOCAL_CLOUD_URL", "").strip()
    if _STAGE == "local"
    else ""
) or STAGE_CLOUD_URLS[_STAGE]
DEFAULT_CLOUD_URL = DEFAULT_CLOUD_URL.rstrip("/")
LDPS_STAGE_RESOLVED = _STAGE

# §6.1 hub provisioning channel — where the Station reaches the assembled OPi to read its
# cpuid + write the cloud-signed binding (flow B step-3). Factory transport = USB-gadget/eth
# link-local; during LAN testing = the OPi's LAN address. Set HUB_HOST to switch.
# See HUB_IDENTITY_DESIGN §6.1 + ../docs/how-to/STAGE_SWITCH.md.
HUB_HOST = os.environ.get("HUB_HOST", "http://192.168.8.158:8000").rstrip("/")
DONGLE_BAUDRATE = 115200

FAKE_UUID = "00000000-0000-4000-a000-000000000000"
TEST_PACK_UUID = "fb000000-0000-4000-a000-000000000001"
