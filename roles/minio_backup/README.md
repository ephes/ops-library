# MinIO Backup Role

Create a snapshot of a single-node MinIO deployment. Snapshots live under `/opt/backups/minio/<prefix>-<timestamp>` and can optionally be archived/fetched to the controller.

By default (`minio_backup_include_data: false`) the role makes a **metadata-only** snapshot: no service stop, no object data, only the IAM and bucket metadata exports plus the configuration files. Object data is expected to be protected elsewhere (bucket replication and snapshots of the replica); the snapshot covers what replication does not carry (users, groups, policies, service accounts, bucket settings, the env file).

With `minio_backup_include_data: true` it makes a cold snapshot that also copies the object data (MinIO stopped for the copy). That full scope refuses a `minio_backup_root` on the root filesystem (`df --output=target` is `/`): a copy of every object there can fill the system disk.

## Disposition

`minio_backup` is an `exception`. This family is intentionally outside the
default Echoport deprecation path because object-storage recovery semantics and
`minio_offsite_replication` are service-specific. Keep using this role when you
need the dedicated MinIO backup workflow.

## What the role does

- Verifies MinIO binaries, service health, credentials, and data directories before touching the filesystem.
- Ensures the MinIO Client (`mc`) is installed (downloads a pinned version if necessary).
- Exports IAM and bucket metadata via `mc admin cluster iam|bucket export` using ephemeral `MC_HOST_*` environment variables (no credentials written to disk).
- Full scope (`minio_backup_include_data: true`): refuses a backup root on the root filesystem, stops the MinIO service, rsyncs every configured data directory to `data/<absolute_path>/`, and copies environment files, systemd units, TLS certs, and optional Traefik config.
- Metadata scope (`minio_backup_include_data: false`, the default): MinIO keeps running; the data directories are neither checked, measured nor copied, the disk check only asks for `minio_backup_metadata_min_free_bytes`, and `metadata.yml` records `scope: metadata` with empty `data_dirs`. The bucket metadata export covers bucket policies, versioning, lifecycle, replication config, tags, quotas and notifications.
- Writes `metadata.yml`, generates a checksum manifest (configurable), and produces a `tar.gz` (or `tar.zst`) archive (mode `0600`) that can be fetched back to the control host.
- With `minio_backup_keep_count: N` (> 0), keeps the N newest `<prefix>-<timestamp>` snapshots (directory and archive) directly under `minio_backup_root` and deletes older ones of the same prefix. Other prefixes and unrelated files are left alone.

Credentials the restore does not need are removed before anything is stored:

- `minio_backup_redact_target_secrets: true` (default) drops every `<bucket>/bucket-targets.json` from the bucket export. MinIO writes each remote target there (XML despite the name) with its access *and secret* key; a replication target set up with root credentials puts the root password in the archive. Without the file a metadata import leaves existing remote targets alone; on a rebuilt MinIO re-run your replication setup to recreate them. An emptied secret is not an option: importing a target without credentials could replace a working one.
- `minio_backup_redact_env_secrets` (default `true` in metadata scope, `false` in full scope) writes the env file copy with the values of `*PASSWORD*`, `*SECRET*` and `*TOKEN*` keys replaced by `REDACTED-BY-MINIO-BACKUP`. `minio_restore` refuses to put such a file back; write the env file from your deployment secrets instead.
- The env mode refuses backslash continuations and multi-line quoted values rather than guess where a secret ends.
- `minio_backup_verify_secret_absent: true` (default) then scans the snapshot (metadata scope: all of it; full scope: the metadata exports) for `minio_root_password` (raw, and as Go's and Python's XML and JSON encoders escape it), including inside ZIP members, and fails the run naming only the files.
- `metadata.yml` records both under `redacted_secrets`.

The helper is `files/redact_backup_secrets.py` (stdlib only, run with `minio_backup_python`, default `python3`); it prints counts, never values, and fails the run when a targets file would survive.

The IAM export contains the secret keys of every user and service account. Keep `minio_backup_root` root-only (`0700`, the default) on encrypted storage, and think twice before `minio_backup_fetch_local: true`.

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
minio_backup_include_data: false         # true = full cold copy (MinIO stopped; not on the root FS)
minio_backup_metadata_min_free_bytes: 104857600
minio_backup_keep_count: 0               # 0 = keep everything
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

Metadata-only example:

```yaml
- hosts: minio
  become: true
  roles:
    - role: local.ops_library.minio_backup
      vars:
        minio_backup_include_data: false
        minio_backup_root: /mnt/cryptdata/backups/minio
        minio_backup_keep_count: 30
        minio_backup_fetch_local: false
        minio_root_user: "{{ vault_minio_root_user }}"
        minio_root_password: "{{ vault_minio_root_password }}"
```

## Output artifacts

- Timestamped snapshot directory with `data<absolute_path>/` (full scope only), `metadata/iam-*.zip`, `config/minio.env`, `systemd/minio.service`, optional `certs/` and `traefik/`.
- `metadata.yml` summarising versions, `scope` (`full` or `metadata`), paths, inclusion flags, and snapshot size.

## Testing

`just test-minio-backup-molecule` builds the platform image and runs `just molecule-test minio_backup`. The scenario starts a real MinIO server in Docker, makes a metadata-only backup with retention while MinIO keeps running, deletes a user, and restores it with `minio_restore` from the metadata snapshot. dl.min.io no longer serves the pinned builds, so the image copies `minio` and `mc` from a MinIO container image (`MINIO_TEST_IMAGE`, default `minio/minio:RELEASE.2025-01-20T14-49-07Z`, available locally or pullable for the Docker host's architecture).

- `manifest.sha256` covering every file (when enabled).
- Optional archive `tar.gz`/`tar.zst` file plus fetched copy on the controller.
