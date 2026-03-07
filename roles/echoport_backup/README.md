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
