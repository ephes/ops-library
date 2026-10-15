# echoport_backup

Registers an Echoport backup service with FastDeploy.

This role sets up a backup runner that can be triggered by Echoport (or directly via FastDeploy) to:

1. Safely backup SQLite databases using `sqlite3 .backup`
2. Archive additional files/directories
3. Create a compressed tarball with manifest
4. Upload to MinIO object storage
5. Output `ECHOPORT_RESULT:{...}` for Echoport to parse

For media backup services (for example homepage/python-podcast templates in this role), object data is
stored in a rolling prefix (`<service>/current/objects`) while each run still writes a per-run manifest
under `ECHOPORT_KEY_PREFIX`.

## Requirements

- FastDeploy must be installed and running
- MinIO server must be accessible
- `sqlite3` package (installed by this role)
- `mc` MinIO client (installed by this role)

## Role Variables

### Required

```yaml
# MinIO configuration - must be provided
echoport_backup_minio_url: "https://minio.example.com"
echoport_backup_minio_access_key: "your-access-key"
echoport_backup_minio_secret_key: "your-secret-key"
```

### Optional

```yaml
# Service identity
echoport_backup_service_name: "echoport-backup"

# MinIO settings
echoport_backup_minio_alias: "minio"
echoport_backup_default_bucket: "backups"
echoport_backup_minio_alias_users: ["{{ echoport_backup_user }}"]
echoport_backup_minio_retired_aliases: []
echoport_backup_minio_prefix_aliases: {}

# FastDeploy API (for service sync)
echoport_backup_api_base: "http://localhost:8000"
echoport_backup_api_token: ""
```

When `echoport_backup_sync_services` is true and the token is set, the role calls
`POST <echoport_backup_api_base>/services/sync`. The call runs with `no_log: true` so the bearer token
never appears in verbose output; a failed sync does not fail the play and is reported by a separate
task that prints only the HTTP status and response body.

### MinIO alias

The role gives `echoport_backup_minio_alias_users` the mc alias
`echoport_backup_minio_alias` with `mc alias import`, which reads the
credentials on stdin. They never appear in a command line, where
`mc alias set <alias> <url> <key> <secret>` would show them in the host's
process list. The alias is imported only when the stored URL or credentials
differ, and every alias in `echoport_backup_minio_retired_aliases` is removed
from those users' mc configuration.

Other plays use the same tasks for their own runner:

```yaml
- name: Configure the mc alias of the delve backup
  ansible.builtin.include_role:
    name: local.ops_library.echoport_backup
    tasks_from: minio_alias
  vars:
    echoport_backup_minio_alias: backup-delve
    echoport_backup_minio_url: "http://127.0.0.1:9001"
    echoport_backup_minio_access_key: "{{ account_user }}"
    echoport_backup_minio_secret_key: "{{ account_secret }}"
    echoport_backup_minio_alias_users: [root]
    echoport_backup_minio_retired_aliases: []
```

The generic runner (`backup.py.j2`) serves several Echoport targets. With
`echoport_backup_minio_prefix_aliases` it uses a separate alias, and so a
separate MinIO account (`minio_deploy`, "Backup accounts"), per target: the
alias is chosen by the first segment of the object key, which is the target
name. A key without an entry uses `echoport_backup_minio_alias`.

```yaml
echoport_backup_minio_prefix_aliases:
  nyxmon: backup-nyxmon
  homelab: backup-homelab
```

## Dependencies

None.

## Example Playbook

```yaml
- hosts: fastdeploy
  roles:
    - role: echoport_backup
      vars:
        echoport_backup_minio_url: "{{ minio_url }}"
        echoport_backup_minio_access_key: "{{ minio_access_key }}"
        echoport_backup_minio_secret_key: "{{ minio_secret_key }}"
        echoport_backup_api_token: "{{ fastdeploy_admin_token }}"
```

## Backup Context Variables

When triggering a backup via FastDeploy/Echoport, the following context variables are used:

| Variable | Description |
|----------|-------------|
| `ECHOPORT_TARGET` | Name of the backup target |
| `ECHOPORT_RUN_ID` | Echoport run ID for tracking |
| `ECHOPORT_DB_PATH` | Path to SQLite database to backup |
| `ECHOPORT_BACKUP_FILES` | Comma-separated list of additional files/dirs |
| `ECHOPORT_BUCKET` | MinIO bucket name |
| `ECHOPORT_KEY_PREFIX` | Object key prefix (e.g., `nyxmon/2024-01-15T02-00-00`) |
| `ECHOPORT_TIMESTAMP` | Backup timestamp |
| `ECHOPORT_MEDIA_OBJECTS_PREFIX` | Optional override for rolling media object prefix (default `<prefix_root>/current`) |

FastDeploy writes the Echoport context to the runner config file nested under
`context.env`; runners must read it from there. The FastDeploy runner
(`fastdeploy_backup.py.j2`) falls back to `<target>/<timestamp>` when
`ECHOPORT_KEY_PREFIX` is empty and refuses to upload when it cannot build a
prefix, so a backup never lands on the shared key `.tar.gz`.

## Media Rolling Mode Notes

Media templates in this role use rolling object storage by default:

- Objects are copied to `.../current/objects` (incremental destination).
- Per-run manifests/checksums are still written under the run key prefix for traceability.
- Point-in-time media restore is not supported in this rolling mode; restore reads from the current objects prefix.

Operational tradeoff:

- Media templates use `rclone copy`, which does not delete objects from the destination if they were removed at source.
- This is safer for backup retention, but destination may accumulate deleted-from-source objects over time.

## Paperless Template Notes

`templates/paperless_backup.py.j2` adds service-specific restore safeguards:

- SQL restore uses `--no-owner` dumps and then reconciles ownership/privileges to the app owner.
- Reconciliation includes `public` tables, views, materialized views, and sequences.
- Rollback path runs service-active and DB app-role checks before reporting rollback success.
- Intended probes:
  - HTTP: `http://127.0.0.1:10030/api/schema/view/` -> `200`
  - DB query: `SELECT COUNT(*) FROM paperless_applicationconfiguration;`

## Homepage / Python Podcast Template Notes

`templates/homepage_production_db_backup.py.j2`, `templates/homepage_staging_backup.py.j2`,
`templates/python_podcast_production_db_backup.py.j2` and
`templates/python_podcast_staging_backup.py.j2` restore a PostgreSQL dump by
dropping and recreating the target database. Every process holding a connection
must be down for that window, not just the web service:

- `SERVICE_NAME` is always stopped before the drop and started after `pg_restore`.
- `AUX_SERVICE_NAMES` lists additional units to stop and start, defaulting to
  `<service>-db-worker` (the Django Tasks worker deployed by `wagtail_deploy`).
  Override per service with `<prefix>_aux_service_names`, e.g.
  `homepage_prod_db_backup_aux_service_names`. The register playbooks are not
  consistent about the `.service` suffix on `<prefix>_service_name` — the
  production-DB ones pass `homepage.service`, the staging ones pass `homepage` —
  so the suffix is stripped before `-db-worker` is appended.
- A failed probe raises rather than reporting the unit absent. Reading a
  transient SSH error as "no such unit" would silently skip the very protection
  this adds.
- Auxiliary units are probed with `systemctl show --property=LoadState` and
  skipped when not present, so a site without a worker restores unchanged.
- Units are started in the order they were stopped, and only removed from the
  pending list once actually started, so the `finally` block retries the rest.

A worker left running during the drop crashes with
`relation "django_tasks_database_dbtaskresult" does not exist`, which reaches
Sentry as the misleading `current transaction is aborted, commands ignored until
end of transaction block` — `django_tasks_db` retries the query inside the same
already-aborted transaction.

## Remote runners and the pinned SSH key

The remote runners (`homepage_*`, `python_podcast_*`, `marina_staging_backup`,
`villakunterbunt_staging_backup`, `heis_production_backup`) run on macmini as
the `deploy` user and SSH to their hosts as `root` with deploy's key. On hosts
where that key is pinned to `echoport_remote_command_guard` (production and
staging), only the commands these templates send are accepted, so:

- every runner except heis calls `scp -O` (classic protocol: the remote side
  sees `scp -f|-t <path>`, which the guard can check; the default SFTP mode
  cannot be path-restricted);
- a new remote command in a template needs a matching guard rule.
  `just test-echoport-remote-command-guard` renders each runner, drives a
  backup and a restore with the network faked, and fails on any command the
  guard would refuse;
- the opt-in python-podcast private media restore (`--include-private-media`)
  is refused by the guard.

The FastDeploy runner (`fastdeploy_backup.py.j2`) does not restore the
services, runner entries and sudoers files retired by the FastDeploy privilege
reduction (`fastdeploy_echoport_backup_retired_entries`,
`fastdeploy_echoport_backup_retired_sudoers`), even from older archives, and it restores other archived sudoers files only when they hold nothing but
narrow per-script rules (older `fastdeploy_register_service` files with
`deploy ALL=(root) NOPASSWD: ALL` are skipped).

## Python Podcast Private Media

`templates/python_podcast_production_db_backup.py.j2` also backs up
python-podcast's private media: contributor voice references and the
known-speaker suggestion sidecar, kept on the server filesystem and off the
public S3 bucket, so neither `pg_dump` nor the S3 media backup covers them.

| Variable | Default | Purpose |
|----------|---------|---------|
| `pp_prod_db_backup_private_media_path` | `/home/python-podcast/site/private_media` | Directory on the backup host; `""` disables the step |
| `pp_prod_db_backup_private_media_max_bytes` | `2147483648` | `du` size guard; a larger tree fails the backup |
| `pp_prod_db_backup_restore_private_media` | `false` | Restore private media to staging by default |
| `pp_prod_db_backup_restore_private_media_path` | `/home/python-podcast/site/private_media` | Restore target on the staging host |
| `pp_prod_db_backup_restore_private_media_owner` | `python-podcast:python-podcast` | Owner of the restored tree |

Backup:

- The directory is probed first. Missing is a warning (recorded as
  `"included": false` in the manifest); a failed probe, a symlink or a
  non-directory fails the backup rather than silently dropping the clips.
- `tar -C <parent> -czf` runs read-only on the source and writes into a fresh
  `mktemp -d` directory (0700, removed afterwards), never a predictable `/tmp`
  file name; the archive is copied back, every member is checked (same safety check as the
  outer archive, plus: under the directory's own name, regular files and
  directories only, uncompressed size within the guard) and it is shipped as
  `private_media/private_media.tar.gz` in the same uploaded archive. The
  manifest's `private_media` entry carries its own `checksum_sha256`.

Restore (staging):

- Skipped by default, and the private media members are not even extracted
  (names are normalized first, and the outer archive may not contain links,
  which this runner never writes), so
  production voice clips do not spread to staging unasked. Staging's own
  private media stays untouched.
- Opt in with `pp_prod_db_backup_restore_private_media: true` or by running
  the runner manually with `--include-private-media`. Nothing in the Echoport
  restore context can switch it on.
- When opted in, the nested archive's checksum and members are verified
  before any service is stopped. The tree is swapped in after `pg_restore`
  while the services are still stopped; the previous tree is moved back if
  the swap fails.

## Django Chat Staging Database Template Notes

`templates/django_chat_staging_db_backup.py.j2` backs up the Django Chat
PostgreSQL database on the staging host (Django Chat has no production). It
runs on macmini as the deploy user and reaches the staging host as root over
SSH with the deploy key; only the deploy user's mc alias touches MinIO.

- Backup: `pg_dump --format=custom` runs on the staging host as `postgres` and
  streams to macmini. `pg_restore --list` must show data for every table in
  `django_chat_staging_db_backup_required_tables`; the row counts of
  `_counted_tables` are read from the dump, not the live database. The
  tarball holds the dump, `manifest.json` (host, database, server version,
  tables, row counts) and `manifest.sha256`. A failed or empty dump, a missing
  table or a stored size that differs fails the run.
- Restore: never touches the live database. After the archive checksum, both
  manifest checksums and the dump are verified, the dump goes into a fresh
  `mktemp -d` directory (root, 0700) on the staging host, is compared by
  SHA-256, and is restored into the new database `<prefix>_<restore id>`
  (`--no-owner --no-privileges --exit-on-error`, an existing name is refused).
  Its row counts are compared with the manifest; the temp directory is removed
  either way. Dropping the scratch database, or swapping it in, is left to
  ops-control.
- `pg_restore` on macmini reads the dump, so its major version must not be
  older than the staging server's; otherwise the run fails at `--list`.
- Variables: `django_chat_staging_db_backup_host`, `_remote_user`, `_db_name`,
  `_postgres_os_user`, `_restore_db_prefix`, `_required_tables`,
  `_counted_tables`, plus the shared `echoport_backup_*` MinIO settings. Media
  is not included: Django Chat keeps it, private voice references too, in S3.

## Graphyard Template Notes

`templates/graphyard_backup.py.j2` is the service-owned same-host runner for Graphyard:

- Backup scope:
  - Django SQLite DB
  - native InfluxDB backup payload from the `graphyard-influxdb` container
  - `/etc/graphyard/graphyard.env`
  - Graphyard systemd units
  - optional `/var/lib/graphyard/influxdb2-config`
- Restore ordering is explicit:
  - restore InfluxDB first
  - restore SQLite second
  - restore env/systemd/config
  - start `graphyard-web`
  - run `manage.py start_agent --run-once`
  - start `graphyard-agent`
  - verify `/v1/health`
- Safety snapshot + rollback use the same native InfluxDB backup format, so rollback restores both
  the time-series state and SQLite state.
- Grafana DB state is intentionally excluded. Dashboards/provisioning live in the Graphyard repo and
  Grafana datasource/admin reconciliation is handled by the Graphyard bootstrap/deploy path.

## Output Format

The backup script outputs a special line for Echoport to parse:

```
ECHOPORT_RESULT:{"success": true, "bucket": "backups", "key": "nyxmon/2024-01-15T02-00-00.tar.gz", "size_bytes": 12345, "checksum_sha256": "abc123...", "manifest": {...}}
```

## License

MIT

## Verified release downloads

The mc installer reuses `minio_backup/tasks/mc_install.yml`. Each deploy reconciles the existing mc binary at `echoport_backup_mc_install_path` (default `/usr/local/bin/mc`) against the pinned SHA-256, replacing a different binary. The default GitHub URL replaces the discontinued dl.min.io endpoint. Override `echoport_backup_mc_download_url` only with an artifact matching `echoport_backup_mc_checksum`. Linux amd64 remains the supported target.

Pinned defaults (checksum map keys identify the release architecture/target):

| Variable | Default |
| --- | --- |
| `echoport_backup_mc_version` | `RELEASE.2025-08-13T08-35-41Z` |
| `echoport_backup_mc_checksum` | `sha256:01f866e9c5f9b87c2b09116fa5d7c06695b106242d829a8bb32990c00312e891` |

To update, bump the version and checksum together. Fetch the SHA-256 from the
project’s published checksum file or release-page asset digest over HTTPS,
and update the source URL comment beside the checksum in `defaults/main.yml`.
Never reuse the old checksum for a new version. Supply matching checksums for
every enabled architecture. Run `just test-root-downloads` before deploying.
