# zfs_dataset

Ansible role to create and manage ZFS datasets with configurable properties.

## Requirements

- ZFS pool must already exist (use `zfs_pool_deploy` role first)
- `zfsutils-linux` package installed (handled by `zfs_pool_deploy`)

## Role Variables

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `zfs_dataset_name` | Full dataset path including pool | `tank/photos` |

### Optional Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `zfs_dataset_properties` | `{}` | Dict of ZFS properties to set |
| `zfs_dataset_macos_compat` | `false` | Enable macOS SMB compatibility |
| `zfs_dataset_mountpoint` | `""` | Custom mountpoint (empty = inherit) |
| `zfs_dataset_mounted` | `true` | Ensure dataset is mounted |
| `zfs_dataset_validate_only` | `false` | Only validate, don't make changes |

### macOS Compatibility Mode

When `zfs_dataset_macos_compat: true`, the following properties are set:

- `xattr=sa` - Store extended attributes in system area
- `acltype=nfsv4` - NFSv4 ACLs for proper macOS permissions
- `casesensitivity=mixed` - Case-insensitive but preserving (create-time only)
- `atime=off` - Disable access time updates

### Common Properties

| Property | Description | Recommended Values |
|----------|-------------|-------------------|
| `recordsize` | Block size | `1M` for large files, `128K` for mixed |
| `compression` | Compression algorithm | `zstd-3` general, `lz4` for already-compressed |
| `refquota` | Reference quota | e.g., `6T` |
| `atime` | Access time updates | `off` for performance |

## Example Playbook

```yaml
- name: Create ZFS datasets
  hosts: storage_server
  become: true
  tasks:
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

    - name: Create photos dataset
      ansible.builtin.include_role:
        name: local.ops_library.zfs_dataset
      vars:
        zfs_dataset_name: tank/photos
        zfs_dataset_macos_compat: true
        zfs_dataset_properties:
          recordsize: 1M
          compression: zstd-3

    - name: Create media dataset (pre-compressed content)
      ansible.builtin.include_role:
        name: local.ops_library.zfs_dataset
      vars:
        zfs_dataset_name: tank/media
        zfs_dataset_macos_compat: true
        zfs_dataset_properties:
          recordsize: 1M
          compression: lz4  # Light compression for already-compressed media
```

## Using with Host Variables

Define datasets in `host_vars/server.yml`:

```yaml
my_zfs_datasets:
  - name: fast/timemachine
    properties:
      recordsize: 1M
      compression: zstd-3
      refquota: 6T
    macos_compat: true

  - name: tank/photos
    properties:
      recordsize: 1M
      compression: zstd-3
    macos_compat: true
```

Then in your playbook:

```yaml
- name: Create datasets from host_vars
  ansible.builtin.include_role:
    name: local.ops_library.zfs_dataset
  loop: "{{ my_zfs_datasets }}"
  loop_control:
    loop_var: dataset
    label: "{{ dataset.name }}"
  vars:
    zfs_dataset_name: "{{ dataset.name }}"
    zfs_dataset_properties: "{{ dataset.properties | default({}) }}"
    zfs_dataset_macos_compat: "{{ dataset.macos_compat | default(false) }}"
```

## Notes

- **Idempotent**: Safe to run multiple times
- **casesensitivity**: Can only be set at creation time. If you need to change it, destroy and recreate the dataset.
- **Encryption**: Datasets inherit encryption from parent pool automatically
- **Quotas**: Use `refquota` for quotas that don't include snapshots, `quota` to include snapshots

## Dependencies

- `zfs_pool_deploy` role (for creating the parent pool)

## License

MIT
