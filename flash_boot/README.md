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

(The more robust long-term fix is cloud-side: publish a merged factory image — or the
bootloader+partitions per version — in the registry so the Station never carries stale boot
assets. Deferred; see the OTA/provisioning discussion.)
