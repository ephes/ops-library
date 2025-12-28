# Hdparm Tune Role

Configure persistent `hdparm` settings (APM, spindown, acoustic management) for specific disks.

## Features
- Writes per-device blocks to `/etc/hdparm.conf`.
- Supports APM (`-B`), spindown timers (`-S`), and acoustic management (`-M`).
- Optionally applies settings immediately (useful without reboot).

## Variables
See `defaults/main.yml` for the full list of variables.

Example configuration:
```yaml
hdparm_tune_devices:
  - device: /dev/disk/by-id/ata-WDC_WD120EFGX-68CPHN0_WD-B00MJ7WD
    apm: 128
    spindown_time: 241
  - device: /dev/disk/by-id/ata-WDC_WD120EFGX-68CPHN0_WD-B00MRZAD
    apm: 128
    spindown_time: 241

hdparm_tune_apply_now: true
```

## Example
```yaml
- hosts: targets
  become: true
  roles:
    - role: local.ops_library.hdparm_tune
      vars:
        hdparm_tune_devices:
          - device: /dev/disk/by-id/ata-WDC_WD120EFGX-68CPHN0_WD-B00MJ7WD
            spindown_time: 241
          - device: /dev/disk/by-id/ata-WDC_WD120EFGX-68CPHN0_WD-B00MRZAD
            spindown_time: 241
        hdparm_tune_apply_now: true
```

## Notes
- Debian/Ubuntu only (uses `/etc/hdparm.conf` via udev).
- `hdparm_tune_apply_now` may spin up drives that are currently in standby.
