# Paperless Restore Role

Restore a Paperless-ngx instance from an archive created by the `paperless_backup` role (or a matching manual snapshot). The role unpacks the requested backup, validates metadata and checksums, optionally captures a pre-restore safety snapshot, stops all Paperless services, restores PostgreSQL plus media/data/configuration files (or runs `document_importer` when available), and finally restarts the services with optional HTTP + PostgreSQL health checks. If the verification phase fails, the captured safety snapshot is replayed automatically as a rollback.

## Capabilities

- Locate a specific archive (or automatically pick the newest artifact under `/opt/backups/paperless`).
- Extract into a dedicated staging directory and verify `metadata.yml` + `manifest.sha256`.
- Capture an optional safety snapshot via the existing `paperless_backup` role (`paperless_restore_safety_backup_prefix`).
- Stop all Paperless services (`paperless`, `paperless-worker`, `paperless-scheduler`, `paperless-consumer`).
- Drop/recreate the `paperless` PostgreSQL database (configurable) and either run the native `document_importer` (preferred) or fall back to replaying `database/paperless.sql`.
- Rsync the `media/` + `data/` directories (and optional `consume/`, `export/`, `logs/` folders) back to `/mnt/cryptdata/paperless` when the raw snapshot path is used.
- Restore `.env`, `gunicorn.conf.py`, systemd unit files, Traefik + scanner SSH configs.
- Restart services, wait for them to report `active`, run a PostgreSQL test query, and hit the Paperless HTTP API.
- Roll back to the automatically captured safety snapshot if verification fails.

## Example

```yaml
- hosts: paperless
  become: true
  roles:
    - role: local.ops_library.paperless_restore
      vars:
        paperless_restore_archive: latest
        paperless_restore_postgres_password: "{{ vault_paperless_db_password }}"
        paperless_restore_safety_backup_vars:
          paperless_backup_exporter_passphrase: "{{ vault_paperless_export_passphrase }}"
```

## Important variables

| Variable | Default | Description |
| --- | --- | --- |
| `paperless_restore_archive` | `latest` | Archive filename or `latest` to auto-select newest `.tar.gz` under `paperless_restore_archive_search_root`. |
| `paperless_restore_validate_checksums` | `true` | Verify `manifest.sha256` before touching the host. |
| `paperless_restore_create_safety_backup` | `true` | Run `paperless_backup` with prefix `pre-restore` to capture a rollback snapshot. |
| `paperless_restore_postgres_*` | defaults from `defaults/main.yml` | Database connection/ownership configuration used for `pg_dump` replay + health checks. |
| `paperless_restore_storage_dirs` | see defaults | Mapping of snapshot folders to destination directories. `required: true` entries must exist in the backup. |
| `paperless_restore_system_files` | `true` | Copy systemd and Traefik/SSH files from the snapshot and reload systemd. |
| `paperless_restore_verify_http` | `true` | Hit `paperless_restore_health_url` after services restart. |
| `paperless_restore_use_importer` | `true` | Attempt `manage.py document_importer` when the exporter artifact is present; automatically falls back to raw pg/sql + rsync on failure. |
| `paperless_restore_importer_flags` | `""` | Optional flags for `document_importer` (only use arguments supported by the importer; exporter-only flags such as `-z/--delete` are not valid here). |
| `paperless_restore_importer_passphrase` | `""` | Optional passphrase passed through `PAPERLESS_PASSPHRASE` for encrypted exports. |
| `paperless_restore_importer_timeout` | `0` | Optional timeout (seconds) for the importer run; `0` disables the limit. |
| `paperless_restore_rollback_on_failure` | `true` | Replay the pre-restore safety snapshot automatically when verification fails. |

### Safety backup variables

The safety snapshot is produced by including `local.ops_library.paperless_backup`. Any dictionary provided in `paperless_restore_safety_backup_vars` is merged into that include, making it easy to forward credentials or change exporter flags.

```yaml
paperless_restore_safety_backup_vars:
  paperless_backup_postgres_password: "{{ vault_paperless_db_password }}"
  paperless_backup_exporter_passphrase: "{{ vault_paperless_export_passphrase }}"
  paperless_backup_include_export: true
```

Set `paperless_restore_create_safety_backup: false` to skip this step (NOT recommended for production hosts).
