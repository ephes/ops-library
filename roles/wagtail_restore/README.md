# wagtail_restore

Restore Wagtail PostgreSQL backups from archives created by `wagtail_backup`.

## Description

This role restores a Wagtail database from a backup archive (or directory), recreates the database, and optionally runs migrations/collectstatic. It can stop and restart the systemd service and supports a dry-run mode to validate inputs without applying changes.

Anything that holds a database connection must be down while the database is dropped and recreated, not just the web service. Set `wagtail_db_worker_enabled: true` (matching your `wagtail_deploy` configuration) so the Django Tasks `db_worker` unit is stopped along with the web service and started again after migrations. A worker left running polls its task table every few seconds and crashes with `relation "django_tasks_database_dbtaskresult" does not exist` the moment the database disappears.

Unlike the main service tasks, the auxiliary unit tasks are not best-effort: they are opt-in, so a unit that fails to stop aborts the run before the database is dropped, and a unit that fails to start fails the run rather than reporting a successful restore with a dead worker. They change run state only — enablement stays owned by `wagtail_deploy`. Auxiliary units are stopped *before* the web service, so such an abort leaves the site up and the database untouched.

Both the stop and the start of auxiliary units are gated on `wagtail_restore_stop_service`, so a run configured not to touch services leaves a worker exactly as it found it.

Any failure inside the restore block triggers a `rescue` that restarts the web service and the auxiliary units best-effort, then re-raises — a failed restore never leaves the site down silently.

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

### Auxiliary Units

```yaml
# Stopped before the drop, started again after migrations.
wagtail_db_worker_enabled: false               # true if the site runs a db_worker
wagtail_db_worker_unit_name: "homepage-db-worker"
wagtail_restore_extra_systemd_units: []        # derived from the two above; override to add more
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
