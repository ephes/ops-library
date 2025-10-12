# MinIO Remove Role

Removes MinIO object storage server from the target host.

## Warning

**This is a destructive operation!** This role will:
- Stop and disable the MinIO service
- Remove MinIO configuration files
- Optionally remove all data directories
- Optionally remove the system user
- Optionally remove MinIO binaries

## Usage

```yaml
- hosts: server
  become: true
  roles:
    - role: local.ops_library.minio_remove
      vars:
        minio_confirm_removal: true  # REQUIRED
        minio_data_dirs:
          - /mnt/cryptdata/minio/data  # Must match deployment
```

## Role Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `minio_confirm_removal` | `false` | **REQUIRED** - Must be `true` to confirm removal |
| `minio_remove_data` | `true` | Remove data directories |
| `minio_remove_user` | `true` | Remove system user and group |
| `minio_remove_binaries` | `true` | Remove minio and mc binaries |
| `minio_data_dirs` | `[/var/lib/minio/data]` | Data directories to remove |

## Data Preservation

To preserve data while removing the service:

```yaml
minio_confirm_removal: true
minio_remove_data: false
minio_remove_user: false
```

## Example: Complete Removal

```bash
# Via ops-control
just remove-one minio

# Direct with ansible-playbook
ansible-playbook -i inventory playbooks/remove-minio.yml \
  -e minio_confirm_removal=true
```

## License

See [LICENSE](../../LICENSE)
