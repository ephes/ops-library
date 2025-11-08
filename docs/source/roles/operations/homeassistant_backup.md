# Home Assistant Backup

Creates on-host and off-host snapshots of Home Assistant configuration, data, logs, Traefik/systemd definitions, and produces a manifest for integrity checks.

## Highlights

- Validates required paths before running.
- Uses `sqlite3 ".backup"` to capture a consistent `home-assistant_v2.db` without stopping the service.
- Rsyncs `config/`, `data/`, `logs/` (optional) to `/opt/backups/homeassistant/<prefix>-<timestamp>/`.
- Copies rendered Traefik file and systemd unit, then writes `metadata.yml` + `manifest.sha256`.
- Optionally creates a `tar.gz` archive and fetches it to the control machine (`~/backups/homeassistant/` by default).

## Key Variables

- `homeassistant_backup_prefix` – naming convention (e.g. `manual`, `pre-deploy`).
- `homeassistant_backup_include_logs` – include/exclude logs.
- `homeassistant_backup_create_archive` / `homeassistant_backup_fetch_local` – enable tarball generation + download.
- `homeassistant_backup_sqlite_path` / `homeassistant_backup_use_sqlite_backup` – database snapshot behaviour.

Usage example:

```yaml
- hosts: macmini
  become: true
  roles:
    - role: local.ops_library.homeassistant_backup
      vars:
        homeassistant_backup_prefix: nightly
        homeassistant_backup_include_logs: false
```
