# Home Assistant Deploy Role

Ansible role that installs and configures a Home Assistant Core instance on bare metal/VM hosts using `uv` managed Python environments. The role mirrors the previous bespoke playbook but adapts it to the shared `ops-library` conventions (idempotent tasks, guard rails, and Traefik integration).

## Features

- Creates the `homeassistant` unix user, directory layout, and Zigbee/Matter udev rule.
- Provisions a Python 3.13 virtualenv via `uv` and installs the `homeassistant` package (optional force-reinstall flag).
- Templated systemd service and Traefik dynamic configuration (single-router layout matching production).
- Optional Matter server install + systemd unit for the Home Assistant Matter integration (`ws://localhost:5580/ws`).
- Optional Matter integration provisioning via the Home Assistant config entry API.
- Optional management of `configuration.yaml`, `secrets.yaml`, and include files with overwrite guards.
- Supports UniFi presence integration credentials sourced from file, generated fallback, or provided variables.

## Key Variables

All tunables live in `defaults/main.yml`; the most important ones are listed below.

| Variable | Default | Description |
| --- | --- | --- |
| `homeassistant_user` | `homeassistant` | Unix user that owns the deployment |
| `homeassistant_site_path` | `/home/homeassistant/site` | Root directory for code/config/logs |
| `homeassistant_manage_uv` | `true` | Run the `uv_install` helper before provisioning Python so `/usr/local/bin/uv` stays current |
| `homeassistant_uv_path` | `/usr/local/bin/uv` | Path to the `uv` binary used for venv + pip (updated automatically when `homeassistant_manage_uv: true`) |
| `homeassistant_python_version` | `3.13.7` | Interpreter version requested from uv |
| `homeassistant_package_spec` | `homeassistant` | Pip spec (`homeassistant==2024.9.3`, etc.) |
| `homeassistant_manage_configuration` | `false` | When `true`, template `configuration.yaml` (only overwrite when `homeassistant_overwrite_config: true`) |
| `homeassistant_manage_secrets` | `false` | Template `secrets.yaml` using UniFi password sources |
| `homeassistant_manage_includes` | `false` | Manage include files defined in `homeassistant_include_files` |
| `homeassistant_overwrite_config` | `false` | Force re-render of configs/includes even if files exist |
| `homeassistant_unifi_password_source` | `file` | `file`, `generate`, or `variable` password discovery |
| `homeassistant_manage_matter_server` | `false` | Install and manage the Matter server systemd unit |
| `homeassistant_matter_server_package_spec` | `python-matter-server[server]` | Pip spec for the Matter server package |
| `homeassistant_matter_server_service_name` | `matter-server` | Systemd service name for the Matter server |
| `homeassistant_matter_server_service_enabled` | `true` | Enable the Matter server service |
| `homeassistant_matter_server_service_state` | `started` | Desired Matter server service state |
| `homeassistant_matter_server_systemd_unit_path` | `/etc/systemd/system/{{ homeassistant_matter_server_service_name }}.service` | Systemd unit path for Matter server |
| `homeassistant_matter_server_port` | `5580` | WebSocket port for Matter server |
| `homeassistant_matter_server_storage_path` | `{{ homeassistant_data_path }}/matter-server` | Persistent storage path for Matter server data |
| `homeassistant_matter_server_vendor_id` | `0xFFF1` | Vendor ID passed to the Matter server |
| `homeassistant_matter_server_fabric_id` | `1` | Fabric ID passed to the Matter server |
| `homeassistant_matter_server_log_level` | `info` | Log level passed to the Matter server |
| `homeassistant_matter_server_log_file` | `{{ homeassistant_logs_path }}/matter-server.log` | Optional log file path |
| `homeassistant_matter_server_restart_on_change` | `true` | Restart the Matter server when templates or packages change |
| `homeassistant_matter_server_chip_factory_dir` | `/data` | Directory for Matter SDK factory data (`chip_factory.ini`) |
| `homeassistant_manage_matter_integration` | `false` | Provision the Matter config entry via the Home Assistant API |
| `homeassistant_matter_integration_url` | `ws://localhost:5580/ws` | WebSocket URL used for the Matter integration |
| `homeassistant_api_url` | `http://localhost:10020` | Base URL for Home Assistant API calls |
| `homeassistant_api_token` | `""` | Long-lived access token used for Home Assistant API calls |
| `homeassistant_api_forwarded_for` | **(auto)** | X-Forwarded-For header value for Home Assistant API requests (defaults to host IPv4 or `127.0.0.1`) |
| `homeassistant_api_forwarded_proto` | `http` | X-Forwarded-Proto header value for Home Assistant API requests |
| `homeassistant_traefik_domain` | **(required)** | Domain for router host (e.g., `home.example.com`) |
| `homeassistant_traefik_entrypoints` | `['web-secure']` | EntryPoints injected into the primary router |

See the defaults file for recorder, logger, timezone, and UniFi integration settings.

## Example Usage

```yaml
- hosts: homelab
  become: true
  roles:
    - role: local.ops_library.homeassistant_deploy
      vars:
        homeassistant_manage_configuration: true
        homeassistant_manage_includes: true
        homeassistant_manage_secrets: true
        homeassistant_external_url: "https://homeassistant.example.com"
        homeassistant_trusted_proxies:
          - "127.0.0.1"
          - "192.168.178.0/24"
        homeassistant_unifi_password_source: variable
        homeassistant_unifi_password_variable: "{{ sops_homeassistant_unifi_password }}"
```

## Notes

- The role intentionally defaults to non-destructive config management. Set `homeassistant_initial_deploy: true` or combine `homeassistant_manage_*` flags with `homeassistant_overwrite_config: true` for the first automation run, then relax them for day‑2 updates.
- Traefik output must match the legacy file byte-for-byte before production cutover. Keep the middleware list/ordering in sync with your production Traefik configuration.
- The role expects `uv` to be preinstalled (handled elsewhere in ops-library). It will fail fast if the binary is missing.
- The Matter server path is best-effort only: upstream supports HAOS add-ons, and non-HAOS installs are explicitly unsupported.
- Matter/Thread traffic depends on IPv6 link-local multicast and correct Router Advertisement handling on the host network.
- When `homeassistant_manage_matter_integration: true`, the role provisions the Matter config entry via the Home Assistant API using `homeassistant_matter_integration_url`. Otherwise, configure the integration via the UI.
- The API token must be a long-lived Home Assistant access token with admin permissions; validation fails if it is missing, too short, or a placeholder like `CHANGE_ME`.
- The server does not require a Bluetooth adapter by default because HA uses the Companion app for commissioning.
- When enabling the Matter server, keep Python >= 3.12 and use `python-matter-server[server]` so native dependencies are installed.
