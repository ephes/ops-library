# wagtail_restore

Restore Wagtail PostgreSQL backups from archives created by `wagtail_backup`.

## Description

This role restores a Wagtail database from a backup archive (or directory), recreates the database, and optionally runs migrations/collectstatic. It can stop and restart the systemd service and supports a dry-run mode to validate inputs without applying changes.

Anything that holds a database connection must be down while the database is dropped and recreated, not just the web service. Set `wagtail_db_worker_enabled: true` (matching your `wagtail_deploy` configuration) so the Django Tasks `db_worker` unit is stopped along with the web service and started again after migrations. A worker left running polls its task table every few seconds and crashes with `relation "django_tasks_database_dbtaskresult" does not exist` the moment the database disappears.

Both the main and auxiliary unit tasks fail closed: they are opt-in, so a unit that fails to stop aborts the run before the database is dropped, and a unit that fails to start fails the run rather than reporting a successful restore with a dead worker. They change run state only — enablement stays owned by `wagtail_deploy`. Auxiliary units are stopped *before* the web service, so such an abort leaves the site up and the database untouched.

Both the stop and the start of auxiliary units are gated on `wagtail_restore_stop_service`, so a run configured not to touch services leaves a worker exactly as it found it.

The compressed SQL must pass `gzip -t` and contain the PostgreSQL completion marker before services stop. Stops fail closed. Before dropping the database, the role takes and verifies a custom-format safety dump of the same database endpoint. SQL is restored with `psql --single-transaction -v ON_ERROR_STOP=1`. If SQL replacement fails, rescue recreates the database from the verified safety dump. A later failure in migrations, static collection or service startup keeps the committed replacement database. When service stopping is enabled, rescue stops services for inspection. A failure before database replacement leaves the database untouched; services already stopped remain stopped. When service stopping is disabled, the caller must keep all writers quiesced through recovery, and rescue leaves their run state untouched.

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

`wagtail_restore_postgres_target_opts` must be empty: the role now owns the
transaction and error-stop options. Nonempty legacy overrides fail validation
before changes.

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

## Retained pre-restore copies

Before replacing live data, the shared `restore_preserve_internal` tasks retain
a timestamped sibling. Ordinary directories are atomically renamed away; mount
points are copied with `cp -a` and verified by checksum and metadata before
emptying their contents. Insufficient space fails before live data changes.
Nested mounts and symlink targets are refused. Quiesce all writers and run only
one restore at a time; when service stopping is disabled, quiescing is the caller’s responsibility.

Wagtail keeps its site in place and always copies it (including media/config);
the verified `database.pre-restore.dump` is stored inside that sibling. This
requires space for both the site and database dump. The site copy is retained
even if taking the database dump fails. Dry run skips safety copies and replacement.

The final report prints the retained path and size in bytes. Restores **never
remove or prune these copies**, including on failure or a later restore. The
owner prunes old copies by hand after inspecting them. Exact path patterns:

- `{{ wagtail_site_path }}.pre-restore-*`

Each `*` is a UTC timestamp plus a random suffix. Failed copy verification may
leave an incomplete sibling; inspect it manually. On failure, use the reported
copy to recover before starting services.

## Task credential handling

The live-database safety dump (`pg_dump`/`pg_restore --list`), the SQL restore (`psql`)
and the rollback from the safety dump (`pg_restore`) read `wagtail_restore_postgres_password`
from a private 0600 passfile in a 0700 temporary directory; the task environment carries only
`PGPASSFILE`. The directory is removed in the restore's `always` section, on success and on
failure. The role requires a nonempty `wagtail_restore_postgres_password`; passwords
containing CR or LF are rejected before any service is stopped; colons and backslashes are
escaped.
