# Navidrome Backup Role

Creates on-host Navidrome backups (data, config, systemd unit, Traefik config, optional logs) with optional archive fetch to the controller.

## Features
- Stops Navidrome for a consistent copy, then rsyncs data/config/logs into a timestamped directory under `{{ navidrome_backup_root }}`.
- Generates a manifest capturing version, paths, and archive name.
- Produces a `.tar.gz` archive by default and fetches it to `{{ navidrome_backup_local_dir }}` when enabled.

## Usage

```yaml
- hosts: media
  become: true
  roles:
    - role: local.ops_library.navidrome_backup
      vars:
        navidrome_backup_prefix: "{{ backup_prefix | default('manual') }}"
        navidrome_backup_fetch_local: true
```

## Key Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `navidrome_backup_root` | `/opt/backups/navidrome` | Remote backup root. |
| `navidrome_backup_prefix` | `manual` | Prefix for backup directory/archive names. |
| `navidrome_backup_create_archive` | `true` | Create compressed archive of the backup directory. |
| `navidrome_backup_fetch_local` | `true` | Fetch archive to the controller. |
| `navidrome_backup_stop_service` | `true` | Stop Navidrome during backup for SQLite safety. |
| `navidrome_backup_include_logs` | `true` | Include `/var/log/navidrome`. |
| `navidrome_backup_retain` | `7` | Keep this many most recent archives (older ones are pruned). |

See `defaults/main.yml` and `roles/navidrome_shared/defaults/main.yml` for the full reference.
