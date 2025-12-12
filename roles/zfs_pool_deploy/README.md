# zfs_pool_deploy

Create and manage ZFS storage pools with native encryption support.

## Description

This role creates ZFS pools with optional native encryption. It supports:
- Single disk, mirror, and RAIDZ topologies
- Native ZFS encryption with passphrase-based keys
- Boot-time automatic key loading via systemd
- Safe defaults requiring explicit confirmation for pool creation

The encryption strategy uses key files stored on the (LUKS-encrypted) root filesystem,
providing two-layer security: LUKS for boot drive, ZFS native for data pools.

## Requirements

- Ubuntu 22.04+ or Debian 12+
- Root/sudo access
- Block devices available for pool creation
- For encrypted pools: SOPS-encrypted passphrase in ops-control

## Role Variables

### Required Variables

```yaml
zfs_pool_name: ""        # Pool name (e.g., "fast", "tank")
zfs_pool_vdevs: []       # Device specifications
zfs_pool_passphrase: ""  # From SOPS - required if encryption enabled
zfs_pool_allow_create: false  # Must be true to create pools
```

### Common Configuration

```yaml
# Pool topology examples
zfs_pool_vdevs:
  # Single disk
  - "/dev/disk/by-id/nvme-..."

  # Mirror (2+ disks)
  - "mirror"
  - "/dev/disk/by-id/ata-..."
  - "/dev/disk/by-id/ata-..."

  # RAIDZ1 (3+ disks)
  - "raidz1"
  - "/dev/disk/by-id/..."
  - "/dev/disk/by-id/..."
  - "/dev/disk/by-id/..."

# Pool properties
zfs_pool_ashift: 12          # 4K sectors (standard)
zfs_pool_autotrim: false     # Enable for SSD/NVMe
zfs_pool_mountpoint: "/{{ zfs_pool_name }}"

# Encryption
zfs_pool_encryption_enabled: true
zfs_pool_encryption_algorithm: "aes-256-gcm"
zfs_pool_keyfile_path: "/root/.zfs-key-{{ zfs_pool_name }}"

# Boot unlock
zfs_pool_configure_boot_unlock: true
```

### Advanced Configuration

```yaml
# Additional pool properties
zfs_pool_properties:
  comment: "My storage pool"

# Root filesystem properties
zfs_pool_filesystem_properties:
  compression: "zstd"
  atime: "off"

# Safety toggles
zfs_pool_validate_only: false   # Dry-run mode
zfs_pool_force_create: false    # DANGEROUS: overwrites existing data
zfs_pool_no_log: true          # Hide passphrases in logs
```

For complete variable list, see `defaults/main.yml`.

## Dependencies

None.

## Example Playbook

### Basic Usage (Single Encrypted Pool)

```yaml
- name: Create ZFS pool
  hosts: storage_server
  become: true
  vars:
    zfs_secrets: "{{ lookup('community.sops.sops', 'secrets/prod/zfs.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.zfs_pool_deploy
      vars:
        zfs_pool_name: "fast"
        zfs_pool_vdevs:
          - "/dev/disk/by-id/nvme-WD_BLACK_SN850X_8000GB_2539A6400382"
        zfs_pool_passphrase: "{{ zfs_secrets.fast_pool_passphrase }}"
        zfs_pool_autotrim: true
        zfs_pool_allow_create: true
```

### Mirror Pool

```yaml
- name: Create mirrored ZFS pool
  hosts: storage_server
  become: true
  vars:
    zfs_secrets: "{{ lookup('community.sops.sops', 'secrets/prod/zfs.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.zfs_pool_deploy
      vars:
        zfs_pool_name: "tank"
        zfs_pool_vdevs:
          - "mirror"
          - "/dev/disk/by-id/ata-WDC_WD120EFGX-68CPHN0_WD-XXXXXXXX"
          - "/dev/disk/by-id/ata-WDC_WD120EFGX-68CPHN0_WD-YYYYYYYY"
        zfs_pool_passphrase: "{{ zfs_secrets.tank_pool_passphrase }}"
        zfs_pool_autotrim: false
        zfs_pool_allow_create: true
```

### Multiple Pools (Loop)

```yaml
- name: Create multiple ZFS pools
  hosts: storage_server
  become: true
  vars:
    zfs_secrets: "{{ lookup('community.sops.sops', 'secrets/prod/zfs.yml') | from_yaml }}"
    pools:
      - name: fast
        vdevs: ["/dev/disk/by-id/nvme-..."]
        autotrim: true
      - name: tank
        vdevs: ["mirror", "/dev/disk/by-id/ata-...", "/dev/disk/by-id/ata-..."]
        autotrim: false
  tasks:
    - name: Create pools
      ansible.builtin.include_role:
        name: local.ops_library.zfs_pool_deploy
      loop: "{{ pools }}"
      loop_control:
        loop_var: pool
      vars:
        zfs_pool_name: "{{ pool.name }}"
        zfs_pool_vdevs: "{{ pool.vdevs }}"
        zfs_pool_passphrase: "{{ zfs_secrets[pool.name ~ '_pool_passphrase'] }}"
        zfs_pool_autotrim: "{{ pool.autotrim | default(false) }}"
        zfs_pool_allow_create: true
```

## Boot Unlock Flow

1. System boots, LUKS root volume unlocked (via dropbear-initramfs or similar)
2. Root filesystem mounted, key files accessible at `/root/.zfs-key-*`
3. `zfs-unlock-<pool>.service` runs before `zfs-mount.service`
4. Service loads encryption key: `zfs load-key <pool>`
5. ZFS mounts datasets automatically

## Security Considerations

- Key files stored with mode 0400, owned by root
- Key files on LUKS-encrypted root = two-layer encryption
- Passphrases managed via SOPS, never in version control
- `no_log: true` prevents passphrase exposure in Ansible output

## Tags

None currently defined.

## Testing

```bash
cd /path/to/ops-library
just test-role zfs_pool_deploy
just lint-role zfs_pool_deploy
```

## License

MIT
