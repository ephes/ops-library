# Homelab Restore

Restores a Homelab deployment from archives created by `homelab_backup`. Validates metadata, manifests, and versions, creates a safety snapshot, then restores database/files/configuration before restarting the service and running health checks.

## Highlights

- Archive discovery via `homelab_restore_archive` (`latest` uses the newest tarball under `/opt/backups/homelab`).
- Metadata validation (slug, timestamp, ops-library version) plus optional checksum verification.
- Dry-run mode (`homelab_restore_dry_run: true`) unpacks/validates without mutating the host and prints the planned actions/downtime.
- Safety snapshot (`/home/homelab/site.pre-restore-<ts>`) with configurable retention.
- Restores SQLite DB, static/media/cache directories, `.env`, systemd unit, and Traefik config; optional static rebuild via `collectstatic`.
- Post-restore checks: Django `check --deploy`, `showmigrations`, SQLite `PRAGMA integrity_check`, and HTTP validation (`homelab_restore_healthcheck_url`).

## Key Variables

- `homelab_restore_archive` – filename or `latest`.
- `homelab_restore_dry_run`, `homelab_restore_allow_version_mismatch`, `homelab_restore_validate_checksums`.
- `homelab_restore_create_safe_snapshot`, `homelab_restore_safe_snapshot_delete`.
- `homelab_restore_restore_env`, `homelab_restore_rebuild_static`, `homelab_restore_verify_http`.
- `homelab_restore_healthcheck_url`, `homelab_restore_expected_content`, `homelab_restore_healthcheck_retries`.

Usage example:

```yaml
- hosts: macmini
  become: true
  roles:
    - role: local.ops_library.homelab_restore
      vars:
        homelab_restore_archive: latest
        homelab_restore_dry_run: false
        homelab_restore_allow_version_mismatch: false
```
