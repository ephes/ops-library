# Home Assistant Remove

Destructively tears down a Home Assistant deployment created by `homeassistant_deploy`. Intended for rebuild scenarios or clean uninstallations.

## Safety

- Requires `homeassistant_confirm_removal: true`.
- CLI wrappers (`just remove-one homeassistant`) prompt for confirmation and optional data preservation.

## Capabilities

- Stops/disables the systemd service and reloads the daemon.
- Removes the Traefik dynamic file and Zigbee/Matter udev rule.
- Deletes the uv virtualenv, site/config/data/log directories (all toggles individually overridable).
- Optionally removes the `homeassistant` user/group.

## Key Variables

- `homeassistant_remove_site_dir`, `homeassistant_remove_config_dir`, etc. – fine-grained directory removal toggles.
- `homeassistant_remove_user`, `homeassistant_remove_group` – preserve or delete the unix account.
- `homeassistant_remove_service`, `homeassistant_remove_traefik`, `homeassistant_remove_udev_rule` – disable specific cleanup steps.

Set any of these to `false` when you need to preserve data for manual inspection before rebuilding. See `roles/homeassistant_remove/defaults/main.yml` for defaults.
