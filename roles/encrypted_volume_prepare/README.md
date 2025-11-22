# Encrypted Volume Prepare Role

Prepare and mount a LUKS-encrypted data volume with keyfile support, UUID verification, and boot-time wiring (crypttab + fstab).

## Features

- Verifies the target block device by LUKS header UUID before acting
- Supports keyfile-based unlock (default) or passphrase-only mode
- Optional safe formatting when the mapper has no filesystem and `encrypted_volume_allow_format` is true
- Writes `/etc/crypttab` and `/etc/fstab` entries for unattended boot and mounts the filesystem
- `encrypted_volume_validate_only` mode to assert configuration without changing disks

## Requirements

- Linux host with LUKS-enabled block device already provisioned
- `cryptsetup` (installed by the role unless `validate_only` is set)
- Ansible collections: `ansible.posix` (for the `mount` module)

## Role Variables

### Required Variables

```yaml
encrypted_volume_device_by_id: ""          # Prefer /dev/disk/by-id/* for path stability
# or
encrypted_volume_device: ""                # Fallback device path if by-id is unavailable

encrypted_volume_expected_luks_uuid: ""    # From `cryptsetup luksUUID /dev/...`
encrypted_volume_passphrase: ""            # From SOPS in ops-control
encrypted_volume_mapper_name: "cryptdata"
encrypted_volume_mount_point: "/mnt/cryptdata"
```

### Common Configuration

```yaml
encrypted_volume_fs_type: "ext4"
encrypted_volume_fs_label: ""              # Optional filesystem label
encrypted_volume_mount_opts: "defaults,noatime"
encrypted_volume_use_keyfile: true         # Store passphrase in a keyfile for unattended boot
encrypted_volume_keyfile_path: "/root/.luks-key-{{ encrypted_volume_mapper_name }}"
encrypted_volume_allow_format: false       # Only format when explicitly true AND no filesystem exists
encrypted_volume_validate_only: false      # Dry-run: assertions only, no changes
```

> Security note: with `encrypted_volume_use_keyfile: true` (default), the passphrase is stored on disk at the keyfile path (0400). Set it to `false` if you prefer manual unlock and do not want the passphrase written locally.

### Advanced Configuration

```yaml
encrypted_volume_packages:
  - cryptsetup
  - cryptsetup-initramfs
encrypted_volume_crypttab_options: "luks"
encrypted_volume_mount_owner: "root"
encrypted_volume_mount_group: "root"
encrypted_volume_mount_mode: "0755"
encrypted_volume_no_log: true              # Mask sensitive values in logs
```

## Example Playbook

```yaml
- hosts: macmini
  become: true
  vars:
    # Prefer by-id for stability
    encrypted_volume_device_by_id: "/dev/disk/by-id/ata-Samsung_SSD_860"
    encrypted_volume_expected_luks_uuid: "e301d851-3454-4b1b-a3a2-5e71f18af8d7"
    encrypted_volume_mapper_name: "cryptdata"
    encrypted_volume_mount_point: "/mnt/cryptdata"
    encrypted_volume_passphrase: "{{ vault_macmini_cryptdata_passphrase }}"
    encrypted_volume_allow_format: false
    encrypted_volume_mount_opts: "defaults,noatime"
  roles:
    - role: local.ops_library.encrypted_volume_prepare
```

### Validate Only

Use `encrypted_volume_validate_only: true` to assert device presence, UUID match, and existing crypttab/fstab entries without opening or mounting the volume.

## Handlers

None.

## Tags

- `encrypted_volume`

## Testing

```bash
# Structural checks
cd /path/to/ops-library
just test-role encrypted_volume_prepare
```

## License

MIT
