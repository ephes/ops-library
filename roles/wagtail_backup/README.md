# wagtail_backup

Create database-only backups for Wagtail services with optional archive and fetch.

## Description

This role snapshots the PostgreSQL database for a Wagtail service into a timestamped backup directory under `/opt/backups/<service>`. It writes a manifest, optionally creates a tar archive, and can fetch the archive to the control machine. By default it does not stop the systemd service.

## Requirements

- PostgreSQL client utilities on the target host
- Ansible collection `community.postgresql`

## Role Variables

### Required Variables

```yaml
wagtail_service_name: "homepage"
wagtail_backup_postgres_password: "..."
```

### Common Configuration

```yaml
wagtail_backup_root: "/opt/backups/homepage"
wagtail_backup_prefix: "manual"
wagtail_backup_stop_service: false
wagtail_backup_fetch_local: true
wagtail_backup_retain: 7
```

### PostgreSQL Settings

```yaml
wagtail_backup_postgres_database: "homepage"
wagtail_backup_postgres_user: "homepage"
wagtail_backup_postgres_host: "localhost"
wagtail_backup_postgres_port: 5432
```

For a complete list of variables, see `roles/wagtail_backup/defaults/main.yml`.

## Dependencies

None.

## Example Playbook

```yaml
- name: Backup Wagtail database
  hosts: wagtail_hosts
  become: true
  vars:
    wagtail_service_name: homepage
    wagtail_backup_postgres_password: "{{ service_secrets.postgres_password }}"
  roles:
    - role: local.ops_library.wagtail_backup
```

## Testing

```bash
cd /path/to/ops-library
just test-role wagtail_backup
```

## License

MIT
