# Hdparm Tune Role

Configure persistent `hdparm` settings (APM, spindown, acoustic management) for specific disks.

## Features
- Writes per-device blocks to `/etc/hdparm.conf`.
- Installs and enables a systemd oneshot (`hdparm-tune.service`) that applies
  the same settings with `hdparm` at every boot.
- Supports APM (`-B`), spindown timers (`-S`), and acoustic management (`-M`).
- Optionally applies settings immediately (useful without reboot).

## Why the boot service
`/etc/hdparm.conf` is applied by Ubuntu's udev hook (`/lib/udev/hdparm`), which
hands APM (`-B`) and spindown (`-S`) to `/usr/lib/pm-utils/power.d/95hdparm-apm`.
That script applies them only when udev flags the disk with
`ID_ATA_FEATURE_SET_APM=1`. Some disks never get that property, for example the
WD120EFGX drives on fractal under Ubuntu 24.04, even though they support APM.
For those disks `hdparm.conf` silently does nothing after a reboot. The drives
then keep their factory APM (128) and have no standby timer, so they never spin
down by themselves. `force_spindown_time` in `hdparm.conf` would cover `-S`
only, not `-B`. The boot service calls `hdparm` directly instead.

To check whether a disk is affected:

```bash
udevadm info -n /dev/sda -q property | grep ID_ATA_FEATURE_SET_APM   # empty = affected
hdparm -B /dev/sda                                                  # shows the live APM level
```

## Variables
See `defaults/main.yml` for the full list of variables.

| Variable | Default | Description |
| --- | --- | --- |
| `hdparm_tune_devices` | `[]` | Devices with `device` and at least one of `apm`, `spindown_time`, `acoustic_management`. |
| `hdparm_tune_apply_now` | `false` | Run `hdparm` during the deploy. Can spin up standby disks. |
| `hdparm_tune_apply_on_boot` | `true` | Install and enable the boot service. `false` or an empty device list removes it. |
| `hdparm_tune_boot_service_name` | `hdparm-tune.service` | Unit name of the boot service. |
| `hdparm_tune_boot_script_path` | `/usr/local/sbin/hdparm-tune-apply` | Script the unit runs. |
| `hdparm_tune_boot_device_wait_sec` | `60` | Seconds the script waits for each device node at boot. |

Example configuration:
```yaml
hdparm_tune_devices:
  - device: /dev/disk/by-id/ata-WDC_WD120EFGX-68CPHN0_WD-B00MJ7WD
    apm: 127
    spindown_time: 241
  - device: /dev/disk/by-id/ata-WDC_WD120EFGX-68CPHN0_WD-B00MRZAD
    apm: 127
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

## Operations
- The deploy only enables the boot service. It does not start it, because
  running `hdparm` can wake standby disks. Use `hdparm_tune_apply_now` for the
  immediate apply, or run `systemctl restart hdparm-tune.service` by hand
  (`restart`, not `start`: with `RemainAfterExit=yes` the unit stays active
  after boot, so a second `start` does nothing).
- Check the last boot's apply with `journalctl -b -u hdparm-tune.service`.
  A missing device or a failing `hdparm` call is logged and makes the unit
  fail; the remaining devices are still applied.
- `-S` values 1–240 are multiples of 5 s, 241–251 are multiples of 30 min.
  The drive may enforce a device-specific minimum, so very short test values
  (for example `-S 12`) can appear to have no effect.

## Notes
- Debian/Ubuntu only.
- APM values 128–254 can prevent automatic spindown on many drives; the role
  prints a warning for them.
- `hdparm_tune_apply_now` may spin up drives that are currently in standby.
