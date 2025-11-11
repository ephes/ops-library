# FastDeploy Restore Role

Restore a FastDeploy instance from a snapshot produced by `fastdeploy_backup`. The role locates the requested artifact, verifies metadata (and optional checksums), optionally captures a safety snapshot before touching the host, restores PostgreSQL plus FastDeploy/deploy-user files, and performs layered health checks (systemd, HTTP endpoint, database query). A rollback path replays the safety snapshot automatically when verification fails.

## Features

- Accepts explicit archive/directory paths or `latest` (auto-select newest `.tar.gz`/`.tar.zst` under `/opt/backups/fastdeploy`).
- Extracts archives into a staging directory and validates `metadata.yml` plus `manifest.sha256` (when `fastdeploy_restore_validate_checksums: true`).
- Optionally captures a safety backup via `fastdeploy_backup` before stopping services.
- Ensures the deploy user’s SOPS key exists (operators must provide it out-of-band).
- Stops the FastDeploy systemd service, drops/recreates the PostgreSQL database, restores `services/`, deploy runner scripts/workspace, `.env`, systemd/Traefik/sudoers files, and restarts the service.
- Re-owns the extracted PostgreSQL dump so the database user can read it before replaying via `psql`.
- Post-restore verification checks systemd status, retries an HTTP health probe, runs a PostgreSQL query, and compares the restored services count to metadata.
- On failure, automatically replays the safety snapshot (if present) and reports the rollback status.

## Key variables

```yaml
fastdeploy_restore_archive: latest
fastdeploy_restore_archive_search_root: /opt/backups/fastdeploy
fastdeploy_restore_validate_checksums: true
fastdeploy_restore_create_safety_backup: true
fastdeploy_restore_safety_backup_prefix: pre-restore
fastdeploy_restore_postgres_database: fastdeploy
fastdeploy_restore_postgres_user: fastdeploy
fastdeploy_restore_postgres_password: ""  # Required if peer auth not available
fastdeploy_restore_services_path: /home/fastdeploy/site/services
fastdeploy_restore_env_file: /home/fastdeploy/site/.env
fastdeploy_restore_deploy_runner_root: /home/deploy/runners
fastdeploy_restore_deploy_workspace: /home/deploy/_workspace
fastdeploy_restore_health_url: http://127.0.0.1:9999/docs
fastdeploy_restore_http_check_retries: 5
fastdeploy_restore_http_check_delay: 2
fastdeploy_restore_dry_run: false
```

See `defaults/main.yml` for the full list.

## Example play

```yaml
- hosts: fastdeploy
  become: true
  vars:
    sops: "{{ lookup('community.sops.sops', 'secrets/prod/fastdeploy.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.fastdeploy_restore
      vars:
        fastdeploy_restore_postgres_password: "{{ sops.db_password }}"
        fastdeploy_restore_health_url: "http://127.0.0.1:9999/docs"
        fastdeploy_restore_archive: "pre-upgrade-20251111T143022.tar.gz"
```

## Workflow overview

1. **Validation** – Resolve archive path, extract if necessary, load metadata, and (optionally) verify checksums.
2. **Safety snapshot** – Run `fastdeploy_backup` with prefix `pre-restore` unless `fastdeploy_restore_create_safety_backup: false` or `fastdeploy_restore_dry_run: true`.
3. **Restore** – Stop FastDeploy, drop/recreate PostgreSQL, sync files from the snapshot into their targets, fix ownership/permissions.
4. **Verification** – Check systemd status, hit health URL, query PostgreSQL for service count, and compare counts to metadata.
5. **Rollback** – If verification fails and a safety snapshot exists, replay it automatically and report the rollback result.
6. **Cleanup** – Remove staging directories when archives were extracted.

## Dry-run mode

Set `fastdeploy_restore_dry_run: true` to validate the archive (metadata + checksums) without stopping services or copying data. Useful for `just restore-fastdeploy-check`.

## Requirements

- FastDeploy host already has the service installed (systemd unit, Traefik config, etc.).
- The deploy user’s SOPS key is provisioned manually before running the restore.
- PostgreSQL utilities (`dropdb`, `createdb`, `psql`) must be available on the host.

## Rollback

When verification fails and `fastdeploy_restore_create_safety_backup` is enabled, the role replays the captured safety snapshot automatically. If both the restore and rollback fail, the role surfaces an explicit error so manual intervention can begin immediately.
