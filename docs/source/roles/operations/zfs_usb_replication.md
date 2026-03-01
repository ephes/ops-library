# ZFS USB Replication

Runs syncoid replication to a USB-attached ZFS pool on a schedule, skipping cleanly when the device is absent.

## Highlights

- Checks for the USB device path before running.
- Imports and exports the USB pool automatically.
- Loads ZFS encryption keys from a key file managed by the role.
- Uses `OnFailure` to trigger a mail alert with recent logs.
- Optional readonly toggle protects target datasets after replication.
- For `recursive: true` + `readonly: true` jobs, existing target parents are auto-set to
  `canmount=off` before `zfs mount -a` to avoid read-only mountpoint creation failures.
- Ensures `/etc/exports.d` exists before mounting to avoid exportfs lock-path errors.

## Key Variables

- `zfs_usb_replication_device` - stable USB device path (`/dev/disk/by-id/...`).
- `zfs_usb_replication_pool` - ZFS pool name on the USB disk.
- `zfs_usb_replication_jobs` - list of syncoid jobs (source -> target).
- `zfs_usb_replication_on_calendar` - schedule for the USB sync.
- `zfs_usb_replication_key` - key material (when key management is enabled).
- `readonly: true` in a job uses `--recvoptions="o readonly=on"` so target datasets stay read-only
  without property toggling between runs.
- `zfs_usb_replication_set_canmount_off_for_readonly_recursive_targets` - defaults to `true`.
- `zfs_usb_replication_exportfs_lock_dir` - defaults to `/etc/exports.d`.

Example usage:

```yaml
- hosts: fractal
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
```
