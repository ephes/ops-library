# Jellyfin Restore Role

Restores Jellyfin from an on-host backup archive (data, config, systemd unit, Traefik config, logs) and brings the service back online.

## Features
- Selects a specific archive or the latest available under `{{ jellyfin_restore_root }}`.
- Unpacks the payload, rsyncs data/config/logs back into place, and reloads systemd/Traefik when needed.
- Ensures Jellyfin directories and permissions are reset before restarting the service.

## Usage

```yaml
- hosts: media
  become: true
  roles:
    - role: local.ops_library.jellyfin_restore
      vars:
        jellyfin_restore_archive: "{{ archive | default('latest') }}"
```

## Key Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `jellyfin_restore_archive` | `latest` | Archive filename or `latest` to auto-select the newest. |
| `jellyfin_restore_root` | `/opt/backups/jellyfin` | Directory containing backup archives. |
| `jellyfin_restore_restart` | `true` | Restart (vs start) the service after restore. |
| `jellyfin_restore_cleanup` | `true` | Remove the staging directory after success. |
| `jellyfin_restore_staging_dir` | `/tmp/jellyfin-restore` | Temporary unpack location; override if restores exceed `/tmp` capacity. |

See `defaults/main.yml` and `roles/jellyfin_shared/defaults/main.yml` for the full variable reference.
