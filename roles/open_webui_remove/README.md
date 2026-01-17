# Open WebUI Remove Role

Safely removes the Open WebUI deployment from a host. Requires explicit confirmation.

## Quick Start

```yaml
- hosts: macmini
  become: true
  roles:
    - role: local.ops_library.open_webui_remove
      vars:
        open_webui_remove_confirm: true
        open_webui_remove_data: false
```

## Role Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `open_webui_remove_confirm` | `false` | Must be `true` to allow removal. |
| `open_webui_remove_site_dir` | `true` | Remove the compose/env directory. |
| `open_webui_remove_data` | `false` | Remove persistent data. |
| `open_webui_remove_traefik_config` | `true` | Remove Traefik dynamic config file. |
| `open_webui_remove_user` | `true` | Remove the service user. |
| `open_webui_remove_group` | `true` | Remove the service group. |

## Behavior

- Stops and disables the systemd unit.
- Removes the unit file and optional Traefik config.
- Optionally deletes data and service user/group.

## Removal Checklist

1. Confirm backups if you plan to delete data.
2. Run the remove role with `open_webui_remove_confirm=true`.
3. Restart Traefik if the dynamic config was removed.
