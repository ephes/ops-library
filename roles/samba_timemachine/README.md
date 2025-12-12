# samba_timemachine

Ansible role to configure Samba with vfs_fruit for macOS Time Machine backups.

## Requirements

- ZFS dataset for Time Machine storage (use `zfs_dataset` role first)
- Ubuntu/Debian system with apt package manager

## Role Variables

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `samba_tm_path` | Path to Time Machine backup location | `/fast/timemachine` |
| `samba_tm_users` | List of users with access | See below |

### User Configuration

```yaml
samba_tm_users:
  - name: timemachine
    password: "{{ sops_secrets.samba_tm_password }}"
```

### Optional Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `samba_tm_share_name` | `timemachine` | Share name in Finder |
| `samba_tm_max_size` | `6T` | Time Machine quota |
| `samba_tm_browseable` | `true` | Show in network browser |
| `samba_tm_workgroup` | `WORKGROUP` | SMB workgroup |
| `samba_tm_server_string` | `Time Machine Backup Server` | Server description |
| `samba_tm_min_protocol` | `SMB3` | Minimum SMB protocol |

### vfs_fruit Options

| Variable | Default | Description |
|----------|---------|-------------|
| `samba_tm_fruit_metadata` | `stream` | Metadata storage mode |
| `samba_tm_fruit_model` | `MacSamba` | Model shown in Finder |
| `samba_tm_fruit_posix_rename` | `true` | Enable POSIX rename |
| `samba_tm_fruit_timemachine` | `true` | Enable Time Machine mode |

### System User

| Variable | Default | Description |
|----------|---------|-------------|
| `samba_tm_system_user` | `timemachine` | System user for file ownership |
| `samba_tm_system_group` | `timemachine` | System group |
| `samba_tm_system_uid` | `2000` | UID for system user |
| `samba_tm_system_gid` | `2000` | GID for system group |

## Example Playbook

```yaml
- name: Configure Time Machine backup server
  hosts: storage_server
  become: true

  vars:
    sops_secrets: "{{ lookup('community.sops.sops', 'secrets/prod/samba.yml') | from_yaml }}"

  tasks:
    - name: Configure Time Machine share
      ansible.builtin.include_role:
        name: local.ops_library.samba_timemachine
      vars:
        samba_tm_path: /fast/timemachine
        samba_tm_max_size: 6T
        samba_tm_users:
          - name: timemachine
            password: "{{ sops_secrets.samba_tm_password }}"
```

## Full Example with ZFS

```yaml
- name: Deploy Time Machine storage
  hosts: storage_server
  become: true

  vars:
    sops_secrets: "{{ lookup('community.sops.sops', 'secrets/prod/fractal-samba.yml') | from_yaml }}"

  tasks:
    # First, create the ZFS dataset
    - name: Create Time Machine dataset
      ansible.builtin.include_role:
        name: local.ops_library.zfs_dataset
      vars:
        zfs_dataset_name: fast/timemachine
        zfs_dataset_macos_compat: true
        zfs_dataset_properties:
          recordsize: 1M
          compression: zstd-3
          refquota: 6T

    # Then, configure Samba
    - name: Configure Time Machine share
      ansible.builtin.include_role:
        name: local.ops_library.samba_timemachine
      vars:
        samba_tm_path: /fast/timemachine
        samba_tm_max_size: 6T
        samba_tm_users:
          - name: tmbackup
            password: "{{ sops_secrets.samba_tm_password }}"
```

## Connecting from macOS

After deployment, connect from your Mac:

1. Open Finder
2. Press Cmd+K (Connect to Server)
3. Enter: `smb://server-ip/timemachine`
4. Authenticate with the configured user
5. Open System Preferences → Time Machine
6. Click "Select Backup Disk"
7. Choose the mounted share

## Security Notes

- Uses SMB3 minimum protocol by default
- Passwords are stored in Samba's encrypted password database
- System user has no login shell
- Time Machine directory has restricted permissions (0770)

## vfs_fruit Configuration

The role configures Samba with Apple's vfs_fruit module for optimal Time Machine compatibility:

- **fruit:metadata = stream**: Stores Apple metadata as NTFS streams (cleanest approach)
- **fruit:model = MacSamba**: Shows Samba server icon in Finder
- **fruit:posix_rename = yes**: Enables atomic renames
- **fruit:time machine = yes**: Enables Time Machine protocol extensions
- **fruit:time machine max size**: Enforces quota at Samba level

This configuration:
- Avoids AppleDouble/._file issues
- Provides proper macOS metadata handling
- Enforces Time Machine quota independently of ZFS

## Dependencies

- `zfs_dataset` role (for creating the storage dataset)

## License

MIT
