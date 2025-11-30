# Navidrome Remove Role

Safely removes Navidrome (service, config, binaries) with confirmation gating and preservation toggles.

## Features
- Stops/disables the `navidrome` service and removes systemd units (including optional rescan timer).
- Deletes config, data, logs, Traefik dynamic config, binaries, and service user/group when enabled.
- Emits a summary so you know what was removed vs preserved.

## Usage

```yaml
- hosts: media
  become: true
  roles:
    - role: local.ops_library.navidrome_remove
      vars:
        navidrome_confirm_removal: true
        navidrome_remove_data: true
        navidrome_remove_logs: true
        navidrome_remove_binary: true
```

## Key Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `navidrome_confirm_removal` | `false` | Must be `true` to run the removal. |
| `navidrome_remove_data` | `true` | Remove data/cache directories. |
| `navidrome_remove_logs` | `true` | Remove log directory. |
| `navidrome_remove_binary` | `true` | Remove installed binary and symlink. |
| `navidrome_remove_traefik_config` | `true` | Remove Traefik dynamic config. |
| `navidrome_remove_user` | `true` | Delete system user/group. |
