# Home Assistant Backup

Creates on-host and off-host snapshots of Home Assistant configuration, data, logs, Traefik/systemd definitions, and produces a manifest for integrity checks.

## Highlights

- Validates required paths before running.
- Uses `sqlite3 ".backup"` to capture a consistent `home-assistant_v2.db` without stopping the service; `.timeout 30000` waits for a committing writer and a failed backup is retried twice.
- Rsyncs `config/`, `data/`, `logs/` (optional) to `/opt/backups/homeassistant/<prefix>-<timestamp>/`.
- Captures Thread + Matter state (`/var/lib/thread` and any Matter Server storage/chip factory dirs outside `data/`).
- Copies rendered Traefik file and systemd unit, then writes `metadata.yml` + `manifest.sha256`.
- Optionally creates a `tar.gz` archive and fetches it to the control machine (`~/backups/homeassistant/` by default).

## Key Variables

- `homeassistant_backup_prefix` – naming convention (e.g. `manual`, `pre-deploy`).
- `homeassistant_backup_include_logs` – include/exclude logs.
- `homeassistant_backup_create_archive` / `homeassistant_backup_fetch_local` – enable tarball generation + download.
- `homeassistant_backup_sqlite_path` / `homeassistant_backup_use_sqlite_backup` – database snapshot behaviour.
- `homeassistant_backup_config_sqlite_databases` – further live SQLite databases below the config directory (default `gps_timeline/gps_timeline.db`, GPS Timeline's long-term location history), copied with `sqlite3 .backup` (same timeout and retries) to the same path in the snapshot; the live file and its `-wal`/`-shm`/`-journal` are excluded from the config rsync. A restore brings them back with the config directory.
- `homeassistant_backup_extra_dirs` – additional directories to include in the snapshot.

Usage example:

```yaml
- hosts: homelab
  become: true
  roles:
    - role: local.ops_library.homeassistant_backup
      vars:
        homeassistant_backup_prefix: nightly
        homeassistant_backup_include_logs: false
```
