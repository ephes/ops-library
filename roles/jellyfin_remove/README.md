# Jellyfin Remove Role

Safely removes Jellyfin (service, packages, config, data, Traefik wiring) with confirmation gating and preservation toggles.

## Features
- Stops/disables the `jellyfin` service and removes the systemd unit.
- Optionally purges Jellyfin packages (jellyfin + ffmpeg variants) and deletes config/data/logs.
- Removes Traefik dynamic config and the service user/group when enabled.
- Emits a summary so you know what was removed vs preserved.

## Usage

```yaml
- hosts: media
  become: true
  roles:
    - role: local.ops_library.jellyfin_remove
      vars:
        jellyfin_confirm_removal: true
        jellyfin_remove_packages: true
        jellyfin_remove_data: true
        jellyfin_remove_logs: true
        jellyfin_remove_config: true
        jellyfin_remove_traefik_config: true
        jellyfin_remove_user: true
```

## Key Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `jellyfin_confirm_removal` | `false` | Must be `true` to run the removal. |
| `jellyfin_remove_packages` | `true` | Purge Jellyfin packages (jellyfin, jellyfin-ffmpeg*). |
| `jellyfin_remove_data` | `true` | Remove `/var/lib/jellyfin`. |
| `jellyfin_remove_logs` | `true` | Remove `/var/log/jellyfin`. |
| `jellyfin_remove_config` | `true` | Remove `/etc/jellyfin`. |
| `jellyfin_remove_traefik_config` | `true` | Remove Traefik dynamic config. |
| `jellyfin_remove_user` | `true` | Delete system user/group. |
