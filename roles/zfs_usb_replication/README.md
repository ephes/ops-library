# zfs_usb_replication

Configure a scheduled USB-attached ZFS replication workflow using `syncoid`, with optional mail alerts.

## Description

This role installs `syncoid` (via the `sanoid` package), writes a USB replication script, and wires a systemd
service + timer. The script checks for the configured USB device path, imports the ZFS pool when present,
loads the encryption key from a key file, runs the configured syncoid jobs, and exports the pool afterwards.
If the USB device is absent, the run logs a clean skip and exits successfully.
When `readonly: true` is set on a job, the script passes `--recvoptions="o readonly=on"` so the target
datasets are created/updated as read-only without toggling properties between runs.
For `recursive: true` + `readonly: true` jobs, the script auto-sets `canmount=off` on existing target
parent datasets before `zfs mount -a` so read-only parents do not block child mountpoint creation.

## Requirements

- ZFS pool on the USB disk, with native encryption enabled.
- A key file stored on the host (managed by this role if `zfs_usb_replication_key_manage=true`).
- Outbound mail relay configured if alerting is enabled (e.g., via `mail_relay_client`).

## Role Variables

### Required

```yaml
zfs_usb_replication_device: /dev/disk/by-id/usb-EXAMPLE
zfs_usb_replication_pool: vault
zfs_usb_replication_key: "{{ vault_usb_key }}"
zfs_usb_replication_jobs:
  - source: tank/replica/fast
    target: vault/replica/fast
    recursive: true
    readonly: true
```

### Common

```yaml
zfs_usb_replication_on_calendar: "Sun 04:00"
zfs_usb_replication_alert_email: "root"
zfs_usb_replication_key_path: "/root/.zfs-key-vault"
zfs_usb_replication_identifier: "usb"
zfs_usb_replication_force_export: true
```

Runtime mount safeguards:
- `zfs_usb_replication_exportfs_lock_dir` defaults to `/etc/exports.d` and is created before mounting.
- `zfs_usb_replication_set_canmount_off_for_readonly_recursive_targets` defaults to `true`.

### Spindown (optional)

```yaml
zfs_usb_replication_spindown_enabled: true
zfs_usb_replication_spindown_pool: "tank"  # pool to check for activity before parking HDDs
zfs_usb_replication_spindown_devices:
  - /dev/disk/by-id/ata-WDC_WD120EFGX-68CPHN0_WD-B00MJ7WD
  - /dev/disk/by-id/ata-WDC_WD120EFGX-68CPHN0_WD-B00MRZAD
```

Notes:
- `zfs_usb_replication_force_export: true` exports the USB pool after each run, even on failure.
- `zfs_usb_replication_spindown_pool` should be the HDD pool (the USB job reads from this pool).
- Spindown is invoked only after a successful replication run.

### Advanced

```yaml
zfs_usb_replication_default_args:
  - "--no-rollback"
zfs_usb_replication_syncoid_path: "/usr/sbin/syncoid"
zfs_usb_replication_timeout_sec: "8h"
zfs_usb_replication_alert_subject_prefix: "[zfs-usb]"
zfs_usb_replication_key_manage: true
zfs_usb_replication_exportfs_lock_dir: "/etc/exports.d"
zfs_usb_replication_set_canmount_off_for_readonly_recursive_targets: true
```

For the full list, see `defaults/main.yml`.

## Dependencies

None.

## Example Playbook

```yaml
- name: Configure USB replication
  hosts: storage
  become: true
  vars:
    zfs_usb_replication_key: "{{ vault_usb_key }}"
  roles:
    - role: local.ops_library.zfs_usb_replication
      vars:
        zfs_usb_replication_device: /dev/disk/by-id/usb-EXAMPLE
        zfs_usb_replication_pool: vault
        zfs_usb_replication_jobs:
          - source: tank/replica/fast
            target: vault/replica/fast
            recursive: true
            readonly: true
        zfs_usb_replication_alert_email: root
```

## Handlers

- `reload systemd` - reloads systemd daemon after unit changes
- `restart zfs-usb-replication-timer` - restarts the timer after updates

## Tags

- `zfs_usb_replication`

## Testing

```bash
just test-role zfs_usb_replication
```

## Changelog

- **1.0.3** (2026-03-01): Hardened readonly recursive USB runs by auto-setting `canmount=off` on existing target parents and ensuring `/etc/exports.d` exists before `zfs mount -a`
- **1.0.2** (2026-01-30): Added force-export and spindown support for USB replication runs
- **1.0.1** (2026-01-29): Added `zfs_usb_replication_identifier` to avoid syncoid snapshot name collisions
- **1.0.0** (2026-01-18): Initial release

## License

MIT

## Author Information

Jochen Wersdoerfer
