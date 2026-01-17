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
        open_webui_remove_compose_files: true
        open_webui_remove_site_dir: true
```

## Role Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `open_webui_remove_confirm` | `false` | Must be `true` to allow removal. |
| `open_webui_remove_compose_files` | `false` | Remove the compose/env files. |
| `open_webui_remove_site_dir` | `false` | Remove the site directory. |
| `open_webui_remove_data` | `false` | Remove persistent data. |
| `open_webui_remove_data_parent` | `false` | Remove the parent directory of the data path. |
| `open_webui_remove_traefik_config` | `false` | Remove Traefik dynamic config file. |
| `open_webui_remove_user` | `false` | Remove the service user. |
| `open_webui_remove_group` | `false` | Remove the service group. |

## Behavior

- Stops and disables the systemd unit.
- Removes the unit file.
- Optionally removes compose/env files, site directory, Traefik config, data directory, parent data directory, and service user/group.

## Usage Notes

- Destructive actions are opt-in; set the corresponding `open_webui_remove_*` flags to `true`.
- If you remove the Traefik config, restart Traefik afterwards.
- Removing the site directory also removes the compose/env files; you can target just those files via `open_webui_remove_compose_files`.

## Removal Checklist

1. Confirm backups if you plan to delete data.
2. Run the remove role with `open_webui_remove_confirm=true`.
3. Restart Traefik if the dynamic config was removed.
