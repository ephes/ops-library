# Home Assistant Deploy

Deploys Home Assistant Core on bare metal/VM hosts using `uv`-managed Python environments, systemd, and Traefik. The role consolidates the legacy in-repo automation into ops-library while adding guard rails for UI-managed configuration.

## Features

- Creates the `homeassistant` user, directory tree, Zigbee/Matter udev rule, and seeded uv virtualenvs.
- Installs Home Assistant via `uv pip` with optional version pinning (`homeassistant_package_spec`).
- Installs optional host-specific integration requirements (`homeassistant_extra_package_specs`) before Home Assistant starts.
- Supports check-mode preflights by running read-only virtualenv inspection
  commands while leaving package and service changes unapplied.
- Reconciles both virtualenvs to the service user and runs inspection/API helper
  commands as that user so Home Assistant can install integration requirements
  at runtime.
- Stops Home Assistant and Matter server before replacing their virtualenvs on Python changes or force reinstalls.
- Templates systemd/Traefik files and manages handlers for reloads/restarts.
- Optional Matter server install + systemd unit for the Home Assistant Matter integration.
- Runs the Matter server in a dedicated virtualenv and validates both Home Assistant Matter imports and Matter server imports after handlers run.
- Optional Matter integration provisioning via the Home Assistant config entry API.
- Optional management of `configuration.yaml`, `secrets.yaml`, and include files with overwrite guards.
- Migrates obsolete role-generated `system_monitor` and `discovery` YAML blocks
  out of existing managed configurations.
- UniFi password discovery supports file, generated, or SOPS-provided secrets.
- Traefik template reproduces the single-router production config (punycode domain, websocket middleware).

## Key Variables

- `homeassistant_manage_configuration` / `homeassistant_overwrite_config` – control templating of `configuration.yaml`.
- `homeassistant_manage_includes` – manage include files like `automations.yaml`.
- `homeassistant_package_spec` – pip spec (for example `homeassistant==<version>`).
- `homeassistant_extra_package_specs` – additional pip specs for integrations whose manifest requirements must be present at startup; pin and maintain these per host.
- `homeassistant_remove_legacy_met_weather_yaml` – remove the old role-generated `weather: platform: met` YAML block when `homeassistant_manage_configuration: true`.
- `homeassistant_manage_uv` – run the shared `uv_install` helper before provisioning Python (keeps `/usr/local/bin/uv` current).
- `homeassistant_manage_matter_server` – install the Matter server package and systemd unit.
- `homeassistant_matter_server_package_spec` – pip spec (for example `python-matter-server[server]==<version>`).
- `homeassistant_matter_server_virtualenv_path` – dedicated uv virtualenv for the Matter server.
- `homeassistant_matter_server_chip_factory_dir` – directory for Matter SDK factory data (`chip_factory.ini`).
- `homeassistant_manage_matter_integration` – provision the Matter config entry via the Home Assistant API.
- `homeassistant_matter_integration_url` – WebSocket URL used for the Matter integration.
- `homeassistant_api_url` / `homeassistant_api_token` – Home Assistant API endpoint and access token for config entry provisioning.
- `homeassistant_api_forwarded_for` / `homeassistant_api_forwarded_proto` – forwarded headers for API calls when `use_x_forwarded_for` is enabled (defaults to host IPv4 or `127.0.0.1`).
- `homeassistant_uv_path` / `homeassistant_python_version` – uv binary and interpreter version.
- `homeassistant_traefik_domain`, `homeassistant_traefik_entrypoints`, `homeassistant_traefik_middlewares` – reverse-proxy behaviour.
- `homeassistant_unifi_password_source` (`file|generate|variable`) plus supporting vars for secrets discovery.

See `roles/homeassistant_deploy/defaults/main.yml` for the full variable catalog.

## Usage

```yaml
- hosts: homelab
  become: true
  roles:
    - role: local.ops_library.homeassistant_deploy
      vars:
        homeassistant_manage_configuration: true
        homeassistant_manage_secrets: true
        homeassistant_manage_includes: true
        homeassistant_unifi_password_source: variable
        homeassistant_unifi_password_variable: "{{ sops_homeassistant_unifi_password }}"
```

After the first automation run, set `homeassistant_overwrite_config: false` (default) so UI-managed YAML remains untouched on subsequent deploys.

## Matter server

Enable the Matter Server alongside Home Assistant by setting `homeassistant_manage_matter_server: true`. The service runs locally from its own uv virtualenv and is intended for the Home Assistant Matter integration.

```yaml
homeassistant_manage_matter_server: true
homeassistant_matter_server_port: 5580
```

To auto-provision the Matter integration, enable API provisioning:

```yaml
homeassistant_manage_matter_integration: true
homeassistant_matter_integration_url: "ws://localhost:5580/ws"
homeassistant_api_token: "{{ vault_homeassistant_api_token }}"
```

The API token must be a Home Assistant long-lived access token with admin
permissions and will fail validation if it is missing, too short, or a
placeholder like `CHANGE_ME`.

Use a host-specific URL (for example `ws://{{ inventory_hostname }}:5580/ws`)
if the Matter server is not on the same host.

When the integration is already present, the role compares the stored URL in
`.storage/core.config_entries` and only reconfigures if it changes.

If you skip API provisioning, add the Matter integration in the Home Assistant UI:

1. Settings -> Devices & services -> Add integration -> Matter
2. Use `ws://localhost:5580/ws` (or the port from `homeassistant_matter_server_port`) as the server URL.

Operational notes:

- Non-HAOS Matter Server deployments are unsupported by upstream and are best-effort.
- IPv6 link-local multicast and Router Advertisement handling must be correct for Matter/Thread traffic.
- The server does not require a Bluetooth adapter by default because Home Assistant uses the Companion app for commissioning.
- `homeassistant_extra_package_specs` is host-specific upgrade debt. Use it only when Home Assistant does not install integration manifest requirements early enough for this uv-managed deployment, keep the pins compatible with the selected Home Assistant version, and revalidate them on every Home Assistant upgrade.
