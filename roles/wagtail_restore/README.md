# wagtail_restore

Restore Wagtail PostgreSQL backups from archives created by `wagtail_backup`.

## Description

This role restores a Wagtail database from a backup archive (or directory), recreates the database, and optionally runs migrations/collectstatic. It stops and restarts the systemd units and supports a dry-run mode that validates the archive and the dump without stopping or changing anything.

### Safety contract

- **The dump is checked first.** Before any unit is stopped (and also in dry-run mode) the
  gzipped plain SQL dump must pass `gzip -t` and end with pg_dump's
  `-- PostgreSQL database dump complete` trailer. A truncated or unfinished dump aborts the run
  with the live database untouched.
- **The stop fails closed.** Auxiliary units are stopped first, then the web service; the run
  then confirms with `systemctl is-active` that every unit is `inactive` or `failed`. Any unit
  still running aborts the run before anything is dropped. With
  `wagtail_restore_stop_service: false` the units must already be stopped, or the run aborts.
- **Safety dump.** After the stop, the role takes a `pg_dump -Fc` of the live database to
  `wagtail_restore_safety_root/<UTC timestamp>/<database>.dump` (default
  `/var/backups/<service>-pre-restore`), checks it with `pg_restore --list` and prints its path.
  It needs free space for one compressed dump of the live database; nothing prunes these
  copies, so remove them once the restored site is verified. When the database does not exist
  yet (a rebuilt host) there is nothing to copy and no dump is taken.
- **One transaction.** The database is dropped and created fresh, then the dump is piped into
  `psql --single-transaction -v ON_ERROR_STOP=1`. The first SQL error aborts the whole load.
- **Rollback, no auto-start.** Any failure after the safety dump (drop, create, load,
  privileges, migrations, collectstatic, index update or the final start) stops the units,
  confirms they are down, recreates the database from the safety dump with
  `pg_restore --single-transaction`, and fails with the safety dump path. The units are left
  **stopped** so the data can be checked first. If a unit cannot be confirmed stopped, nothing is
  rolled back and the message says so.
- The staging directory with the unpacked dump is removed in an `always` section, also after a
  failure.

Anything that holds a database connection must be down while the database is dropped and recreated, not just the web service. Set `wagtail_db_worker_enabled: true` (matching your `wagtail_deploy` configuration) so the Django Tasks `db_worker` unit is stopped along with the web service and started again after migrations. A worker left running polls its task table every few seconds and crashes with `relation "django_tasks_database_dbtaskresult" does not exist` the moment the database disappears.

Auxiliary units change run state only — enablement stays owned by `wagtail_deploy`. They are stopped *before* the web service, so a worker that will not stop aborts the run with the site still up and the database untouched. Their start after a successful restore is gated on `wagtail_restore_stop_service`, so a run configured not to touch services does not start them.

## Requirements

- PostgreSQL client utilities (`psql`, `pg_dump`, `pg_restore`, `dropdb`, `createdb`) and
  `gzip` on the target host
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
wagtail_restore_cleanup: true                  # staging is removed also after a failure
wagtail_restore_dry_run: false                 # true: validate archive and dump only
wagtail_restore_safety_root: "/var/backups/homepage-pre-restore"
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
wagtail_restore_postgres_admin_user: "homepage"   # drops/creates the DB and takes the safety dump
wagtail_restore_postgres_target_opts: ""          # extra psql options for the load
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
