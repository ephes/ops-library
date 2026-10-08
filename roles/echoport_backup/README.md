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

# FastDeploy API (for service sync)
echoport_backup_api_base: "http://localhost:8000"
echoport_backup_api_token: ""
```

When `echoport_backup_sync_services` is true and the token is set, the role calls
`POST <echoport_backup_api_base>/services/sync`. The call runs with `no_log: true` so the bearer token
never appears in verbose output; a failed sync does not fail the play and is reported by a separate
task that prints only the HTTP status and response body.

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
