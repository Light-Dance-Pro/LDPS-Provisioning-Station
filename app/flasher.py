"""esptool wrapper — flash Edge-Node firmware in background thread."""
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import threading
import time

from app.config import FIRMWARE_DIR
from app.utils import log


class Flasher:
    def __init__(self, ws_manager=None):
        self.ws = ws_manager
        self._thread: threading.Thread | None = None
        self.running = False
        self.progress = 0
        self.status = "idle"
        self.error = ""

    def start(self, port: str, firmware_dir: str = FIRMWARE_DIR) -> bool:
        if self.running:
            return False

        bootloader = os.path.join(firmware_dir, "bootloader.bin")
        partitions = os.path.join(firmware_dir, "partitions.bin")
        firmware = os.path.join(firmware_dir, "firmware.bin")

        for f in [bootloader, partitions, firmware]:
            if not os.path.exists(f):
                self.error = f"Missing: {os.path.basename(f)}"
                return False

        # SHA256 verification against manifest (if present)
        manifest = os.path.join(firmware_dir, "firmware_manifest.json")
        if os.path.exists(manifest):
            if not self._verify_sha256(manifest, firmware_dir):
                return False

        self._thread = threading.Thread(
            target=self._run, args=(port, bootloader, partitions, firmware), daemon=True
        )
        self._thread.start()
        return True

    def start_three(self, port: str, bootloader: str, partitions: str, firmware: str) -> bool:
        """Factory (USB) flash for a BLANK chip: bootloader@0x0 + partitions@0x8000 +
        app@0x10000. A blank ESP32-S3 has no bootloader / partition-table, so the
        registry's app-only OTA image flashed ALONE at 0x0 clobbers the boot region →
        boot-loop (image hash mismatch). This writes all three at their correct offsets.
        bootloader+partitions are the Station's bundled stable boot assets (flash_boot/);
        firmware is the per-version app from the cloud registry cache."""
        if self.running:
            return False
        for f in (bootloader, partitions, firmware):
            if not f or not os.path.exists(f):
                self.error = f"Missing flash file: {os.path.basename(f or '?')}"
                return False
        self._thread = threading.Thread(
            target=self._run, args=(port, bootloader, partitions, firmware), daemon=True
        )
        self._thread.start()
        return True

    def start_image(self, port: str, image_path: str) -> bool:
        """Flash a single MERGED factory image at 0x0 (a real bootloader+partitions+app
        merged image — NOT the registry's app-only firmware.bin, which must go through
        start_three). Kept for a future cloud-delivered firmware.factory.bin."""
        if self.running:
            return False
        if not image_path or not os.path.exists(image_path):
            self.error = f"Missing image: {image_path}"
            return False
        self._thread = threading.Thread(target=self._run_image, args=(port, image_path), daemon=True)
        self._thread.start()
        return True

    def _run_image(self, port: str, image: str):
        self.running = True
        self.progress = 0
        self.status = "flashing"
        self.error = ""
        self._broadcast()
        old_stdout, old_stderr = sys.stdout, sys.stderr
        captured = io.StringIO()
        flashed = False
        try:
            import esptool
            sys.stdout = captured
            sys.stderr = captured
            esptool.main([
                "--port", port, "--baud", "921600", "--chip", "esp32s3",
                "write_flash", "0x0", image,
            ])
            flashed = True
        except SystemExit as e:
            flashed = (e.code == 0)
            if not flashed:
                self.error = captured.getvalue()[-300:]
        except Exception as e:
            self.error = str(e)
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
        self._finish_flash(port, flashed)

    def _verify_sha256(self, manifest_path: str, firmware_dir: str) -> bool:
        """Verify firmware files against SHA256 hashes in manifest."""
        try:
            with open(manifest_path) as f:
                manifest = json.load(f)
        except Exception as e:
            self.error = f"Manifest read error: {e}"
            return False

        for entry in manifest.get("files", []):
            name = entry.get("name", "")
            expected_hash = entry.get("sha256", "")
            if not name or not expected_hash:
                continue
            path = os.path.join(firmware_dir, name)
            if not os.path.exists(path):
                self.error = f"Manifest references missing file: {name}"
                return False
            actual_hash = _sha256_file(path)
            if actual_hash != expected_hash:
                self.error = f"SHA256 mismatch for {name}"
                log(f"[Flash] SHA256 mismatch: {name} expected={expected_hash[:12]}... got={actual_hash[:12]}...", "ERROR")
                return False

        log("[Flash] SHA256 verification passed")
        return True

    def _verify_node_boot(self, port: str, attempts: int = 5) -> bool:
        """Post-flash boot self-check: confirm the node actually BOOTS THE APP, not just
        that esptool wrote bytes. A wrong-offset / corrupt / partition-mismatch flash leaves
        the chip boot-looping in the bootloader — esptool still exits 0, so without this a bad
        flash 'succeeds' and only surfaces steps later (e.g. Format SD 'no Format-OK ack'). A
        booted app answers 'i' with FW/MAC; a boot-loop answers nothing."""
        from app import node_serial
        for _ in range(max(1, attempts)):
            time.sleep(2.0)
            try:
                ident = node_serial.read_identity(port)
            except Exception:
                ident = {}
            if ident.get("fw") or ident.get("mac"):
                return True
        return False

    def _finish_flash(self, port: str, flashed: bool):
        """Shared flash tail: gate 'done' on the post-flash boot self-check so a bad image
        fails HERE (loudly, at the Flash step) instead of silently downstream."""
        if flashed:
            self.status = "verifying"
            self.progress = 95
            self._broadcast()
            if self._verify_node_boot(port):
                self.status = "done"
                self.progress = 100
            else:
                self.status = "error"
                self.error = ("flash wrote OK but the node did NOT boot the app after reset "
                              "(bad image / wrong offset / partition-scheme mismatch) — "
                              "post-flash self-check failed")
        else:
            self.status = "error"
            if not self.error:
                self.error = "flash failed"
        self.running = False
        self._broadcast()
        log(f"[Flash] {self.status}: {self.error or 'OK'}")

    def _run(self, port: str, bootloader: str, partitions: str, firmware: str):
        self.running = True
        self.progress = 0
        self.status = "flashing"
        self.error = ""
        self._broadcast()

        old_stdout = sys.stdout
        old_stderr = sys.stderr
        captured = io.StringIO()

        flashed = False
        try:
            import esptool
            sys.stdout = captured
            sys.stderr = captured

            esptool.main([
                "--port", port,
                "--baud", "921600",
                "--chip", "esp32s3",
                "write_flash",
                "0x0000", bootloader,
                "0x8000", partitions,
                "0x10000", firmware,
            ])
            flashed = True
        except SystemExit as e:
            flashed = (e.code == 0)
            if not flashed:
                self.error = captured.getvalue()[-300:]
        except Exception as e:
            self.error = str(e)
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
        self._finish_flash(port, flashed)

    def _broadcast(self):
        if self.ws:
            self.ws.broadcast("flash", {
                "running": self.running,
                "progress": self.progress,
                "status": self.status,
                "error": self.error,
            })

    @staticmethod
    def list_firmware(firmware_dir: str = FIRMWARE_DIR) -> list[dict]:
        if not os.path.isdir(firmware_dir):
            return []
        files = []
        for name in ["bootloader.bin", "partitions.bin", "firmware.bin"]:
            path = os.path.join(firmware_dir, name)
            if os.path.exists(path):
                files.append({
                    "name": name,
                    "size": os.path.getsize(path),
                    "sha256": _sha256_file(path),
                })
        return files

    @staticmethod
    def generate_manifest(firmware_dir: str = FIRMWARE_DIR) -> str:
        """Generate firmware_manifest.json from current firmware files."""
        files = []
        for name in ["bootloader.bin", "partitions.bin", "firmware.bin"]:
            path = os.path.join(firmware_dir, name)
            if os.path.exists(path):
                files.append({
                    "name": name,
                    "size": os.path.getsize(path),
                    "sha256": _sha256_file(path),
                })
        manifest = {"version": "1.0", "files": files}
        manifest_path = os.path.join(firmware_dir, "firmware_manifest.json")
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)
        log(f"[Flash] Manifest generated: {len(files)} files")
        return manifest_path


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
