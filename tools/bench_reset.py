#!/usr/bin/env python3
"""Return a bench node to BLANK on both sides so the full flow can be re-run.

Re-running the provisioning flow on the same board fails by design, in two places:

  1. Station: the node still carries its UUID in NVS (0x9000 - a reflash writes
     0x0/0x8000/0x10000 and never touches it), so finalize returns
     409 ALREADY_PROVISIONED before the cloud is contacted.
  2. Cloud: the hardware serial already has an identity, so request-uuid returns
     409 SERIAL_EXISTS.

Both are anti-counterfeit guards and are left intact. This script performs the
legitimate reset instead: clear the node over USB ('U'), then revoke the cloud row.
After it runs, the board is genuinely blank and the flow re-runs end to end.

LOCAL DEV ONLY: the revoke goes straight at the local Supabase with the service-role
key, which is the admin path. Never point this at UAT or prod.
"""
import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

PI = "192.168.50.172"
KEY = "/Users/jeff1112/.ssh/id_ed25519_orangepi"
STATION = f"http://{PI}:9000"
SB = "http://127.0.0.1:54321"
CLOUD_ENV = "/Users/jeff1112/Desktop/lightdancepro/Light-Dance-Pro-AI-uat/cloud/.env"
DEFAULT_MAC = "28:84:85:A2:BF:E8"


def ssh(cmd: str) -> str:
    r = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-i", KEY, "-o", "IdentitiesOnly=yes",
         f"root@{PI}", cmd],
        capture_output=True, text=True, timeout=60)
    return r.stdout.strip()


def post(url: str, body: dict, headers: dict = None, timeout: int = 40):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", **(headers or {})})
    try:
        return json.load(urllib.request.urlopen(req, timeout=timeout))
    except urllib.error.HTTPError as e:
        return {"_http": e.code, "_body": e.read().decode()[:200]}


ap = argparse.ArgumentParser()
ap.add_argument("--mac", default=DEFAULT_MAC, help="node USB MAC / hardware serial")
a = ap.parse_args()
mac = a.mac.upper()

# 1. resolve the node's port from its MAC (ttyACM numbering shifts on replug)
link = f"/dev/serial/by-id/usb-Espressif_USB_JTAG_serial_debug_unit_{mac}-if00"
port = ssh(f"readlink -f {link} 2>/dev/null || true")
if not port:
    sys.exit(f"ABORT: no board with MAC {mac} attached to the Pi")
print(f"1. node {mac} -> {port}")

# 2. clear the identity over USB ('U'): uuid + sig + key_id + owner out of NVS.
#    No reflash needed - and a reflash would not do it anyway.
r = post(f"{STATION}/api/provision/clear", {"port": port})
print(f"2. clear -> {json.dumps(r)[:160]}")

# 3. revoke every live cloud row for this serial, so request-uuid stops
#    returning SERIAL_EXISTS.
svc = [l.split("=", 1)[1].strip().strip("\"'")
       for l in open(CLOUD_ENV) if l.startswith("SUPABASE_SERVICE_ROLE_KEY=")][0]
H = {"apikey": svc, "Authorization": "Bearer " + svc}
q = (f"{SB}/rest/v1/nodes?select=node_uuid,provision_status"
     f"&hardware_serial=eq.{urllib.parse.quote(mac)}")
rows = json.load(urllib.request.urlopen(
    urllib.request.Request(q, headers={**H, "Accept-Profile": "hardware"}), timeout=20))
live = [r_ for r_ in rows if r_.get("provision_status") != "revoked"]
if not live:
    print("3. cloud: no live row for this serial (already clear)")
for r_ in live:
    out = post(f"{SB}/rest/v1/rpc/revoke_node",
               {"p_node_uuid": r_["node_uuid"], "p_admin": None,
                "p_reason": "bench re-test reset"},
               {**H, "Content-Profile": "hardware"})
    print(f"3. revoked {r_['node_uuid']} -> {json.dumps(out)[:120]}")

# 4. verify the node really reads back blank
ident = ssh(
    "cd /opt/ldps-provisioning-station && CLOUD_URL=http://192.168.50.15:3737 "
    f".venv/bin/python -c \"from app.node_serial import read_identity; "
    f"i=read_identity('{port}'); print(i.get('uuid') or 'BLANK')\" 2>/dev/null | tail -1")
print(f"4. node identity now: {ident}")
print("\nBoard is blank on both sides - re-run the flow from Start."
      if ident == "BLANK" else
      "\nWARNING: node still reports an identity - clear did not take.")
