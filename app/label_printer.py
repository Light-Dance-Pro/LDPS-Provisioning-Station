"""Box-label printing — 58mm USB thermal printer (ESC/POS raster).

The label is the operator's only copy of the recovery key (§3.4: the cloud returns
it once, in plaintext, and never again), so it is printed the moment a unit's
commit lands — see `_log_success` in routes/provision.py.

Printing NEVER fails a provision: the unit is already committed in the cloud by the
time we get here, so a paper jam or an unplugged printer must not turn a good unit
into an error. Failures are logged and the label can be re-printed from the CLI
(`print_label.py --uuid <uuid>`).

Layout mirrors the UI preview (templates/index.html): QR -> <cloud>/verify/<uuid>,
product + FW, UUID, recovery key, made date, MAC.
"""
from __future__ import annotations

import os
import threading
from datetime import datetime

from app.utils import log

WIDTH = 384          # 58mm @ 203dpi printable width, in dots
DEVICE = os.environ.get("LABEL_PRINTER", "/dev/usb/lp0")
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_M = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"


def render(data: dict, cloud_url: str):
    """Render the label to a 1-bit PIL image, cropped to its content."""
    from PIL import Image, ImageDraw, ImageFont
    import qrcode

    uuid = data.get("uuid", "")
    verify = f"{(cloud_url or '').rstrip('/')}/verify/{uuid}"

    f_title = ImageFont.truetype(FONT_B, 30)
    f_small = ImageFont.truetype(FONT, 17)
    f_mono = ImageFont.truetype(FONT_M, 19)
    f_key = ImageFont.truetype(FONT_M, 30)

    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,
                       box_size=6, border=2)
    qr.add_data(verify)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("1")
    if qr_img.width > WIDTH - 20:
        qr_img = qr_img.resize((WIDTH - 20, WIDTH - 20), Image.NEAREST)

    img = Image.new("1", (WIDTH, 900), 1)      # 1 = white
    d = ImageDraw.Draw(img)
    y = 8

    def centre(text, font):
        w = d.textbbox((0, 0), text, font=font)[2]
        d.text(((WIDTH - w) // 2, y), text, font=font, fill=0)

    centre(f"LDPS · {data.get('product_type') or 'Node'}", f_title); y += 38
    centre(f"FW {data.get('firmware_ver') or '?'}", f_small); y += 26

    img.paste(qr_img, ((WIDTH - qr_img.width) // 2, y))
    y += qr_img.height + 14

    d.text((10, y), "DEVICE UUID", font=f_small, fill=0); y += 22
    # A 36-char UUID will not fit one 384-dot line at this mono size; split on the
    # final hyphen group so both halves stay legible.
    head, _, tail = uuid.rpartition("-")
    d.text((10, y), head or uuid, font=f_mono, fill=0); y += 24
    if tail:
        d.text((10, y), tail, font=f_mono, fill=0); y += 24
    y += 8

    if data.get("recovery_key"):
        d.text((10, y), "RECOVERY KEY", font=f_small, fill=0); y += 24
        d.text((10, y), data["recovery_key"], font=f_key, fill=0); y += 40

    made = (data.get("timestamp") or "")[:10] or datetime.now().strftime("%Y-%m-%d")
    d.text((10, y), f"Made {made}", font=f_small, fill=0); y += 24
    if data.get("mac"):
        d.text((10, y), f"MAC {data['mac']}", font=f_small, fill=0); y += 30

    return img.crop((0, 0, WIDTH, min(y + 8, img.height)))


def escpos(img) -> bytes:
    """GS v 0 raster bit-image. PIL '1' mode has 0 = black; ESC/POS has 1 = print."""
    img = img.convert("1")
    w_bytes = (img.width + 7) // 8
    px = img.load()
    raw = bytearray()
    for yy in range(img.height):
        for xb in range(w_bytes):
            byte = 0
            for bit in range(8):
                x = xb * 8 + bit
                if x < img.width and px[x, yy] == 0:
                    byte |= 0x80 >> bit
            raw.append(byte)
    out = bytearray(b"\x1b\x40")                    # ESC @  initialise
    out += b"\x1d\x76\x30\x00"                      # GS v 0, mode 0
    out += bytes([w_bytes & 0xFF, (w_bytes >> 8) & 0xFF,
                  img.height & 0xFF, (img.height >> 8) & 0xFF])
    out += raw
    out += b"\n\n\n\n"                              # feed clear of the tear bar
    return bytes(out)


def print_label(data: dict, cloud_url: str, device: str = DEVICE) -> dict:
    """Render + send one label. Returns {ok, error} — never raises."""
    try:
        if not os.path.exists(device):
            return {"ok": False, "error": f"no printer at {device}"}
        payload = escpos(render(data, cloud_url))
        with open(device, "wb") as f:
            f.write(payload)
        return {"ok": True, "bytes": len(payload)}
    except Exception as e:                                   # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def print_async(data: dict, cloud_url: str) -> None:
    """Fire-and-forget: the provision response must not wait on paper."""
    def _run():
        r = print_label(data, cloud_url)
        if r.get("ok"):
            log(f"[Label] printed {data.get('uuid')} ({r['bytes']} bytes)")
        else:
            log(f"[Label] print failed for {data.get('uuid')}: {r.get('error')} "
                f"— re-print with: print_label.py --uuid {data.get('uuid')}", "WARNING")

    threading.Thread(target=_run, daemon=True).start()
