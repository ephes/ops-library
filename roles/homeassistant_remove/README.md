# Home Assistant Remove Role

Destructively removes a Home Assistant Core deployment that was managed by `homeassistant_deploy`. The role stops the systemd service, deletes the unit file, removes Traefik/udev resources, wipes the install directories, and optionally deletes the system user and group.

## Safety

Set `homeassistant_confirm_removal: true` (e.g. via `just remove-one homeassistant`) before running. Without confirmation the role aborts.

## Defaults

| Variable | Default | Description |
| --- | --- | --- |
| `homeassistant_service_name` | `homeassistant` | Systemd unit to stop/remove |
| `homeassistant_systemd_unit_path` | `/etc/systemd/system/homeassistant.service` | Unit file path to delete |
| `homeassistant_traefik_config_path` | `/etc/traefik/dynamic/homeassistant.yml` | Dynamic config file to remove |
| `homeassistant_site_path` | `/home/homeassistant/site` | Base directory for config/data/logs |
| `homeassistant_remove_user` | `true` | Remove the `homeassistant` user (and group) |
| `homeassistant_remove_site_dir` | `true` | Delete `/home/homeassistant/site` |

Toggle any of the `homeassistant_remove_*` flags to preserve specific resources when needed.
