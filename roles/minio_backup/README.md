# MinIO Backup Role

Create a cold snapshot of a single-node MinIO deployment including IAM/bucket metadata, object data, and all supporting configuration. Snapshots live under `/opt/backups/minio/<prefix>-<timestamp>` and can optionally be archived/fetched to the controller.

## What the role does

- Verifies MinIO binaries, service health, credentials, and data directories before touching the filesystem.
- Ensures the MinIO Client (`mc`) is installed (downloads a pinned version if necessary).
- Exports IAM and bucket metadata via `mc admin cluster iam|bucket export` using ephemeral `MC_HOST_*` environment variables (no credentials written to disk).
- Stops the MinIO service, rsyncs every configured data directory to `data/<absolute_path>/`, and copies environment files, systemd units, TLS certs, and optional Traefik config.
- Writes `metadata.yml`, generates a checksum manifest (configurable), and produces a `tar.gz` (or `tar.zst`) archive that can be fetched back to the control host.

## Key variables

```yaml
minio_backup_root: /opt/backups/minio
minio_backup_prefix: manual
minio_data_dirs:
  - /var/lib/minio/data
minio_env_file: /etc/default/minio
minio_service_unit: /etc/systemd/system/minio.service
minio_certs_dir: /etc/minio/certs
minio_traefik_config_path: /etc/traefik/dynamic/minio.yml
minio_root_user: ""        # REQUIRED (provide via SOPS)
minio_root_password: ""    # REQUIRED (provide via SOPS)
minio_mc_bin_path: /usr/local/bin/mc
minio_backup_export_iam: true
minio_backup_export_bucket_metadata: true
minio_backup_include_tls_certs: "{{ minio_tls_enable }}"
minio_backup_include_traefik: true
minio_backup_disk_check_enabled: true
minio_backup_use_delete: true
minio_backup_create_archive: true
minio_backup_archive_format: tar.gz
minio_backup_generate_checksums: true
minio_backup_fetch_local: true
```

See `defaults/main.yml` for the full list.

## Example play

```yaml
- hosts: minio
  become: true
  roles:
    - role: local.ops_library.minio_backup
      vars:
        minio_backup_prefix: "pre-upgrade"
        minio_root_user: "{{ vault_minio_root_user }}"
        minio_root_password: "{{ vault_minio_root_password }}"
        minio_backup_fetch_local: true
```

## Output artifacts

- Timestamped snapshot directory with `data<absolute_path>/`, `metadata/iam-*.zip`, `config/minio.env`, `systemd/minio.service`, optional `certs/` and `traefik/`.
- `metadata.yml` summarising versions, paths, inclusion flags, and snapshot size.
- `manifest.sha256` covering every file (when enabled).
- Optional archive `tar.gz`/`tar.zst` file plus fetched copy on the controller.
