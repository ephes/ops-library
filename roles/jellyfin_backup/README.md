# Jellyfin Backup Role

Creates on-host Jellyfin backups (data, config, systemd unit, Traefik config, optional logs) with optional archive fetch to the controller.

## Features
- Stops Jellyfin for a consistent copy, then rsyncs data/config/logs into a timestamped directory under `{{ jellyfin_backup_root }}`.
- Captures the installed package version in a manifest for auditing.
- Produces a `.tar.gz` archive by default and fetches it to `{{ jellyfin_backup_local_dir }}` when enabled.

## Usage

```yaml
- hosts: media
  become: true
  roles:
    - role: local.ops_library.jellyfin_backup
      vars:
        jellyfin_backup_prefix: "{{ backup_prefix | default('manual') }}"
        jellyfin_backup_fetch_local: true
```

## Key Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `jellyfin_backup_root` | `/opt/backups/jellyfin` | Remote backup root. |
| `jellyfin_backup_prefix` | `manual` | Prefix for backup directory/archive names. |
| `jellyfin_backup_create_archive` | `true` | Create compressed archive of the backup directory. |
| `jellyfin_backup_fetch_local` | `true` | Fetch archive to the controller. |
| `jellyfin_backup_stop_service` | `true` | Stop Jellyfin during backup for data consistency. |
| `jellyfin_backup_include_logs` | `true` | Include `/var/log/jellyfin`. |
| `jellyfin_backup_retain` | `7` | Keep this many most recent archives (older ones are pruned). |

See `defaults/main.yml` and `roles/jellyfin_shared/defaults/main.yml` for the full reference.
