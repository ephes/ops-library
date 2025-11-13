# MinIO Restore Role

Rehydrate a single-node MinIO deployment from a snapshot produced by `minio_backup`. The role handles archive discovery/upload, checksum validation, safety backups, data/config restoration, and post-restore verification.

## What the role does

- Resolves the requested archive (`latest` by default) from `/opt/backups/minio`, or uploads one from the controller cache. When `minio_restore_prefer_latest_directory` is true, the newest extracted snapshot directory is used before falling back to archives.
- Extracts the archive into a staging directory (supports `tar.gz` and `tar.zst`) and validates `metadata.yml` plus the checksum manifest.
- Ensures the MinIO Client (`mc`) is installed, then (optionally) snapshots the current data/config into a safety directory for automatic rollback.
- Stops MinIO, restores `.env`, systemd unit, TLS certificates, Traefik config, and rsyncs every recorded data directory from the snapshot.
- Starts MinIO, waits for the health endpoint, and replays bucket/IAM metadata via `mc admin cluster bucket|iam import` using ephemeral `MC_HOST_*` environment variables.
- Verifies the restored instance with `mc admin info` / `mc ls`, and cleans up staging + (optionally) the safety snapshot.

## Key variables

```yaml
minio_restore_archive: latest
minio_restore_archive_search_root: /opt/backups/minio
minio_restore_local_cache: "{{ lookup('env', 'HOME') }}/backups/minio"
minio_restore_staging_dir: /tmp/minio-restore
minio_restore_prefer_latest_directory: false
minio_restore_validate_checksums: true
minio_restore_create_safety_backup: true
minio_restore_cleanup_safety_backup: true
minio_restore_dry_run: false
minio_restore_restore_system_files: true
minio_restore_restore_traefik: true
minio_restore_restore_iam: true
minio_restore_restore_bucket_metadata: true
minio_restore_verify_http: true
minio_restore_check_disk_space: true
minio_restore_disk_space_multiplier: 2.0
minio_root_user: ""        # REQUIRED (provide via SOPS)
minio_root_password: ""    # REQUIRED (provide via SOPS)
minio_mc_bin_path: /usr/local/bin/mc
minio_mc_version/checksum/download_url: match `minio_deploy`
```

See `defaults/main.yml` for the full reference.

## Example play

```yaml
- hosts: minio
  become: true
  roles:
    - role: local.ops_library.minio_restore
      vars:
        minio_root_user: "{{ vault_minio_root_user }}"
        minio_root_password: "{{ vault_minio_root_password }}"
        minio_restore_archive: "pre-upgrade-20251113T101500.tar.gz"
```

## Safety & verification

- When `minio_restore_create_safety_backup` is true, each existing data directory and the current config/systemd files are copied to `{{ minio_restore_safety_backup_prefix }}-<timestamp>` in `/tmp/minio-restore/`. Any failure during the restore triggers an automatic rollback from that snapshot.
- Health checks target `http://<bind_host>:<api_port>/minio/health/live` by default; override `minio_restore_health_path` if you expose MinIO differently.
- `mc` metadata imports use URL-encoded credentials and IPv6-safe hostnames; no aliases/config files are persisted on disk.
