# Open WebUI Venv Remove Role

Safely removes the Open WebUI venv-based deployment from a host. Requires explicit confirmation.

## Quick Start

```yaml
- hosts: macmini
  become: true
  roles:
    - role: local.ops_library.open_webui_venv_remove
      vars:
        open_webui_remove_confirm: true
        open_webui_remove_site_dir: true
        open_webui_remove_data: true
```

## Role Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `open_webui_remove_confirm` | `false` | Must be `true` to allow removal. |
| `open_webui_remove_env_file` | `false` | Remove the env file (`open-webui.env`). |
| `open_webui_remove_venv` | `false` | Remove the virtualenv directory. |
| `open_webui_remove_site_dir` | `false` | Remove the site directory. |
| `open_webui_remove_data` | `false` | Remove persistent data. |
| `open_webui_remove_log_dir` | `false` | Remove log directory. |
| `open_webui_remove_traefik_config` | `false` | Remove Traefik dynamic config file. |
| `open_webui_remove_user` | `false` | Remove the service user. |
| `open_webui_remove_group` | `false` | Remove the service group. |

## Behavior

- Stops and disables the systemd unit.
- Removes the unit file.
- Optionally removes the env file, venv, site directory, data directory, logs, Traefik config, and service user/group.

## Usage Notes

- Destructive actions are opt-in; set the corresponding `open_webui_remove_*` flags to `true`.
- Removing the site directory also removes the venv and env file if they are inside it.
- If you remove the Traefik config, restart Traefik afterwards.

## Removal Checklist

1. Confirm backups if you plan to delete data.
2. Run the remove role with `open_webui_remove_confirm=true`.
3. Restart Traefik if the dynamic config was removed.
