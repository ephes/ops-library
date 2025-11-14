# Homelab Backup

Creates end-to-end snapshots of the Homelab Django service: SQLite database, static/media directories, cache (optional), `.env`, and supporting configs. Produces metadata + checksum manifest and optionally fetches a compressed archive to the control machine.

## Highlights

- Validates required paths and records ops-library + git metadata for traceability.
- Uses `sqlite3 ".backup"` with automatic fallback to an offline snapshot that stops Homelab briefly when needed.
- Rsyncs static/media/cache directories to `/opt/backups/homelab/<prefix>-<timestamp>/`.
- Copies `.env`, systemd unit, and Traefik config into the backup for audit and restore parity.
- Generates `metadata.yml`, `manifest.sha256`, an optional `tar.gz` archive, and fetches it to `~/backups/homelab/` when enabled.

## Key Variables

- `homelab_backup_prefix` – naming convention for backup directories/archives (default `manual`).
- `homelab_backup_include_media`, `homelab_backup_include_static`, `homelab_backup_include_cache` – toggle captured directories.
- `homelab_backup_force_stop` / `homelab_backup_sqlite_retries` – control SQLite snapshot behaviour.
- `homelab_backup_create_archive`, `homelab_backup_fetch_local`, `homelab_backup_local_dir` – archive + fetch settings.

Usage example:

```yaml
- hosts: macmini
  become: true
  roles:
    - role: local.ops_library.homelab_backup
      vars:
        homelab_backup_prefix: "pre-upgrade"
        homelab_backup_include_cache: false
        homelab_backup_fetch_local: true
```
