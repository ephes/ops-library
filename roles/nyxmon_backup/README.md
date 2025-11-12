# Nyxmon Backup Role

Creates timestamped Nyxmon snapshots under `/opt/backups/nyxmon` and fetches the compressed archive back to the control machine by default.

## Features

- Validates site, media, static, logs, `.env`, systemd, Traefik, and database paths before running.
- Optionally stops `nyxmon.service`/`nyxmon-monitor.service` (default) to guarantee SQLite consistency.
- Uses `sqlite3 .backup` when enabled, otherwise copies the database via rsync.
- Rsyncs media/static/logs (with include flags for cache/static/logs) plus config files, systemd units, and Traefik config.
- Captures metadata + SHA256 manifest, compresses to `tar.gz`, and fetches archives to `~/backups/nyxmon`.

## Key Variables

```yaml
nyxmon_backup_root: /opt/backups/nyxmon
nyxmon_backup_prefix: manual
nyxmon_site_path: /home/nyxmon/site
nyxmon_backup_sqlite_path: "{{ nyxmon_site_path }}/db.sqlite3"
nyxmon_backup_stop_services: true
nyxmon_backup_include_logs: true
nyxmon_backup_include_cache: false
nyxmon_backup_include_static: true
nyxmon_backup_generate_checksums: true
nyxmon_backup_create_archive: true
nyxmon_backup_archive_format: tar.gz
nyxmon_backup_fetch_local: true
nyxmon_backup_local_dir: "{{ lookup('env', 'HOME') }}/backups/nyxmon"
```

## Example Playbook

```yaml
- name: Backup Nyxmon
  hosts: macmini
  become: true
  roles:
    - role: local.ops_library.nyxmon_backup
      vars:
        nyxmon_backup_prefix: pre-deploy
```

This produces `/opt/backups/nyxmon/pre-deploy-YYYYmmddTHHMMSS/…` plus a `.tar.gz` that is fetched to `~/backups/nyxmon/`.
