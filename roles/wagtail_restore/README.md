# wagtail_restore

Restore Wagtail PostgreSQL backups from archives created by `wagtail_backup`.

## Description

This role restores a Wagtail database from a backup archive (or directory), recreates the database, and optionally runs migrations/collectstatic. It can stop and restart the systemd service and supports a dry-run mode to validate inputs without applying changes.

## Requirements

- PostgreSQL client utilities on the target host
- Ansible collection `community.postgresql`

## Role Variables

### Required Variables

```yaml
wagtail_service_name: "homepage"
wagtail_restore_archive: "latest"  # or a specific archive name/path
wagtail_restore_postgres_password: "..."
```

### Common Configuration

```yaml
wagtail_restore_root: "/opt/backups/homepage"
wagtail_restore_stop_service: true
wagtail_restore_restart: true
wagtail_restore_cleanup: true
```

### PostgreSQL Settings

```yaml
wagtail_restore_postgres_database: "homepage"
wagtail_restore_postgres_user: "homepage"
wagtail_restore_postgres_host: "localhost"
wagtail_restore_postgres_port: 5432
```

For a complete list of variables, see `roles/wagtail_restore/defaults/main.yml`.

## Dependencies

None.

## Example Playbook

```yaml
- name: Restore Wagtail database
  hosts: wagtail_hosts
  become: true
  vars:
    wagtail_service_name: homepage
    wagtail_restore_archive: "latest"
    wagtail_restore_postgres_password: "{{ service_secrets.postgres_password }}"
  roles:
    - role: local.ops_library.wagtail_restore
```

## Testing

```bash
cd /path/to/ops-library
just test-role wagtail_restore
```

## License

MIT
