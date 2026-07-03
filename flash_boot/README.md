# Factory-flash boot assets (bootloader + partition table)

A **blank** ESP32-S3 needs three regions written to boot: `bootloader.bin` @ `0x0`,
`partitions.bin` @ `0x8000`, and the app @ `0x10000`. The cloud firmware registry only
carries the **app** image (`firmware.bin`, used for OTA, which writes to an app partition
on an already-booting node). So the Station bundles the stable bootloader + partition table
here and flashes all three for a factory (USB) flash — see `app/routes/flash.py` `flash_start`.

Layout: `flash_boot/<product-slug>/{bootloader.bin,partitions.bin}` (slug matches
`firmware_cache._slug`, e.g. `LED Node` -> `LED-Node`).

**These are versioned with the node's PARTITION SCHEME, not the app version** — they only
change if the partition table / bootloader config changes. Re-copy them from the Edge-Node
build (`.pio/build/esp32s3/{bootloader,partitions}.bin`) whenever the partition scheme changes.
Source of the current files: Edge-Node FW 2.3.38 build (partition scheme as of 2026-07).

## Decision (2026-07-03): the boot pack stays here, NOT in the cloud registry

The app image is **per-version** (OTA and factory flash share the SAME `firmware.bin`); the
bootloader + partition table are a **PRODUCT CONSTANT** — they change only if you change the
partition scheme / bootloader logic, a rare, deliberate event, never with the app version.

Putting a factory image (or boot assets) in the registry **per version** was considered and
**rejected**: it would force the admin panel to upload a second, matched artifact every release —
pure error surface (upload the wrong one / forget one / version-skew) for a thing that never
changes with the app. So:

- **Admin panel is unchanged** — one app image per version (used for OTA *and* factory).
- **This boot pack** is a reviewed station-repo commit, re-done ONLY when the partition
  scheme / bootloader changes.
- The flasher's **post-flash boot self-check** (`flasher._verify_node_boot`) makes any drift
  (stale boot pack, wrong offset, corrupt image) fail **LOUDLY at the Flash step** — never a
  silent brick that surfaces downstream.

Why OTA never touches the bootloader: it is the immutable trusted anchor that performs the
boot-select + rollback; if OTA could overwrite it and failed mid-write the node would brick with
no rollback path. So bootloader/partitions are deliberately out of OTA scope — which is exactly
why factory flash must supply them and OTA need not.
