# FastDeploy Backup Role

Create a complete FastDeploy snapshot (database, services tree, deploy-runner artifacts, system integration files, and metadata) under `/opt/backups/fastdeploy/<prefix>-<timestamp>` and optionally fetch an archive back to the controller.

## What it does

- Validates required FastDeploy and deploy-user paths (site, `.env`, `services/`, `/home/deploy/runners`) before copying data.
- Estimates disk usage and enforces a configurable overhead ratio (default 1.5×) before writing into the backup root.
- Captures the installed FastDeploy version using the uv/virtualenv interpreter so metadata reflects the deployed build.
- Dumps the PostgreSQL database via `pg_dump` (as the `postgres` role by default) over the local unix socket unless a host is provided, copying the SQL file into `database/fastdeploy.sql`.
- Rsyncs the FastDeploy `services/` tree plus deploy-runner scripts (excluding the SOPS age key for security) into the snapshot.
- Optionally includes the deploy user’s workspace and exports `journalctl -u fastdeploy` logs when enabled.
- Copies `.env`, systemd units, Traefik config, sudoers rules, and any other integration files needed to rehydrate the service.
- Writes `metadata.yml`, generates a checksum manifest, produces a `tar.gz` (default) or `tar.zst` archive, and can fetch the archive to the controller.

## Security notes

- The deploy user’s SOPS age key (`~deploy/.config/sops/age/keys.txt`) is **never** copied. Operators must store it separately (password manager, hardware token, etc.) and provision it manually before restoring.
- Snapshot directories live under `/opt/backups/fastdeploy` owned by `root:root` with mode `0700` by default; adjust via vars if your policy differs.
- PostgreSQL dumps, `.env`, and sudoers files contain sensitive credentials. Treat archives as secrets and store/fetch them only over trusted channels.

## Key variables

```yaml
fastdeploy_backup_root: /opt/backups/fastdeploy
fastdeploy_backup_prefix: manual
fastdeploy_backup_site_path: /home/fastdeploy/site
fastdeploy_backup_services_path: "{{ fastdeploy_backup_site_path }}/services"
fastdeploy_backup_env_file: "{{ fastdeploy_backup_site_path }}/.env"
fastdeploy_backup_runner_root: /home/deploy/runners
fastdeploy_backup_include_workspace: false
fastdeploy_backup_include_logs: false
fastdeploy_backup_postgres_database: fastdeploy
fastdeploy_backup_postgres_user: postgres
fastdeploy_backup_postgres_password: ""  # REQUIRED when peer auth is unavailable
fastdeploy_backup_postgres_host: ""      # Empty = unix socket (peer auth)
fastdeploy_backup_create_archive: true
fastdeploy_backup_archive_format: tar.gz
fastdeploy_backup_fetch_local: true
```

See `defaults/main.yml` for the full reference.

## Example play

```yaml
- hosts: fastdeploy
  become: true
  roles:
    - role: local.ops_library.fastdeploy_backup
      vars:
        fastdeploy_backup_prefix: "pre-upgrade"
        fastdeploy_backup_postgres_password: "{{ vault_fastdeploy_db_password }}"
        fastdeploy_backup_include_logs: true
```

This produces `/opt/backups/fastdeploy/pre-upgrade-YYYYmmddTHHMMSS/` and `pre-upgrade-…tar.gz`, then fetches the archive to `~/backups/fastdeploy/` on the controller.

## Output artifacts

- Timestamped directory tree containing `database/fastdeploy.sql`, `services/`, `deploy_runners/`, optional `deploy_workspace/`, exported logs, and system configs.
- `metadata.yml` summarizing timestamp, host, FastDeploy version, component toggles, archive info, and extra metadata you provide.
- `manifest.sha256` covering every file in the snapshot (when `fastdeploy_backup_generate_checksums: true`).
- Optional tar archive (gzip by default) plus local copy when `fastdeploy_backup_fetch_local` is enabled.
