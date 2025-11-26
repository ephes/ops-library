# Paperless Backup Role

Create a full Paperless-ngx snapshot (application exporter + PostgreSQL + storage/config files) under `/opt/backups/paperless/<prefix>-<timestamp>` and optionally pull a compressed archive back to the control host.

## What it does

- Verifies all critical Paperless paths (virtualenv, `.env`, media/data mounts, optional consume/export/logs directories).
- Runs `document_exporter` via the Paperless virtualenv (with configurable flags and optional passphrase) into `<backup>/exporter`.
- Executes `pg_dump` with configurable options into `<backup>/database/paperless.sql`.
- Rsyncs external storage directories (media/data plus optional consume/export/logs).
- Copies `.env`, `gunicorn.conf.py`, all Paperless systemd units, Traefik + scanner SSH configs, and any extra files you list.
- Verifies free disk space under the backup root before copying data (configurable thresholds).
- Writes `metadata.yml`, generates a checksum manifest, builds a `tar.gz`/`tar.zst` archive, can `fetch` it to the control machine, and prints the final artifact size.

## Requirements

- Host must already have Paperless installed (virtualenv + manage.py directory) and `document_exporter` working.
- `pg_dump`, `rsync`, `tar`, and `sha256sum` need to be present.
- PostgreSQL credentials should allow `pg_dump` (peer auth or password via `paperless_backup_postgres_password`).
- Sufficient free space under `paperless_backup_root` (default `/opt/backups/paperless`) to hold at least one full snapshot.

## Role Variables (excerpt)

```yaml
paperless_backup_root: /opt/backups/paperless
paperless_backup_prefix: manual
paperless_backup_site_root: /home/paperless/site
paperless_backup_manage_dir: "{{ paperless_backup_site_root }}/paperless-ngx/src"
paperless_backup_virtualenv: "{{ paperless_backup_site_root }}/.venv"
paperless_backup_env_file: "{{ paperless_backup_site_root }}/.env"
paperless_backup_media_path: /mnt/cryptdata/paperless/media
paperless_backup_data_path: /mnt/cryptdata/paperless/data
paperless_backup_consume_path: /mnt/cryptdata/paperless/consume
paperless_backup_export_path: /mnt/cryptdata/paperless/export
paperless_backup_include_consume: false
paperless_backup_include_export: false
paperless_backup_include_logs: false
paperless_backup_exporter_enabled: true
paperless_backup_exporter_flags: "-z --delete"
paperless_backup_exporter_passphrase: ""
paperless_backup_exporter_clean_target: true
paperless_backup_postgres_database: paperless
paperless_backup_postgres_user: paperless
paperless_backup_postgres_password: ""   # optional, use peer auth otherwise
paperless_backup_postgres_become_user: postgres
paperless_backup_postgres_dump_options: "--clean --if-exists --no-owner"
paperless_backup_create_archive: true
paperless_backup_archive_format: tar.gz   # or tar.zst
paperless_backup_fetch_local: true
paperless_backup_fetch_method: synchronize
paperless_backup_disk_check_enabled: true
paperless_backup_disk_overhead_ratio: 1.15   # require 15% headroom relative to estimated snapshot size
paperless_backup_report_size: true
paperless_backup_config_files:
  - { src: "{{ paperless_backup_env_file }}", dest: "config/paperless.env" }
  - { src: "{{ paperless_backup_site_root }}/gunicorn.conf.py", dest: "config/gunicorn.conf.py" }
paperless_backup_systemd_units:
  - /etc/systemd/system/paperless.service
  - /etc/systemd/system/paperless-worker.service
  - /etc/systemd/system/paperless-scheduler.service
  - /etc/systemd/system/paperless-consumer.service
paperless_backup_traefik_config_path: /etc/traefik/dynamic/paperless.yml
paperless_backup_ssh_config_path: /etc/ssh/sshd_config.d/sftp-scanner.conf
paperless_backup_extra_files: []  # [{ src: "/etc/foo", dest: "extras/foo" }]
```

See `defaults/main.yml` for the full list.

## Example Play

```yaml
- hosts: paperless
  become: true
  roles:
    - role: local.ops_library.paperless_backup
      vars:
        paperless_backup_prefix: pre-migration
        paperless_backup_include_consume: true
        paperless_backup_include_export: true
        paperless_backup_include_logs: true
        paperless_backup_postgres_password: "{{ vault_paperless_db_password }}"
        paperless_backup_exporter_passphrase: "{{ vault_paperless_export_passphrase }}"
        paperless_backup_local_dir: "{{ lookup('env', 'HOME') }}/backups/paperless"
```

This produces `/opt/backups/paperless/pre-migration-YYYYMMDDThhmmss/…` plus `pre-migration-…tar.gz` fetched to the control host.

## Output artifacts

- Full directory tree under `paperless_backup_root` (database dump, exporter output, media/data rsyncs, config/system files).
- `metadata.yml` describing version/flags/paths used (timestamp reflects play start time).
- `manifest.sha256` of every file (optional).
- Optional `tar.gz` / `tar.zst` archive and local copy on the control machine.

## Security notes

- `document_exporter` receives its passphrase via the `PAPERLESS_PASSPHRASE` environment variable, so secrets do not show up in process listings or Ansible logs (the task automatically flips `no_log` on when a passphrase is set).
- `pg_dump` falls back to the `PGPASSWORD` environment variable only when `paperless_backup_postgres_password` is provided; prefer peer authentication (leave it empty) if possible.
