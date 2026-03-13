# Home Assistant Deploy Role

Ansible role that installs and configures a Home Assistant Core instance on bare metal/VM hosts using `uv` managed Python environments. The role mirrors the previous bespoke playbook but adapts it to the shared `ops-library` conventions (idempotent tasks, guard rails, and Traefik integration).

## Features

- Creates the `homeassistant` unix user, directory layout, and Zigbee/Matter udev rule.
- Provisions a Python 3.13 virtualenv via `uv` and installs the `homeassistant` package (optional force-reinstall flag).
- Templated systemd service and Traefik dynamic configuration (single-router layout matching production).
- Optional Matter server install + systemd unit for the Home Assistant Matter integration (`ws://localhost:5580/ws`).
- Optional Matter integration provisioning via the Home Assistant config entry API.
- Optional OpenThread Border Router (OTBR) integration provisioning via the Home Assistant config entry API.
- Optional Wyoming integration provisioning via the Home Assistant config entry API.
- Optional area-registry updates via the Home Assistant admin WebSocket API.
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
| `homeassistant_manage_otbr_integration` | `false` | Provision the OTBR config entry via the Home Assistant API |
| `homeassistant_otbr_integration_url` | `http://127.0.0.1:8081` | REST URL used for the OpenThread Border Router integration |
| `homeassistant_manage_wyoming_integration` | `false` | Provision the Wyoming config entry via the Home Assistant API |
| `homeassistant_wyoming_host` | `""` | Hostname or IP for the Wyoming server Home Assistant should add |
| `homeassistant_wyoming_port` | `10300` | TCP port for the Wyoming server |
| `homeassistant_manage_assist_pipeline_stt_engine` | `false` | Update the preferred Assist pipeline (or `homeassistant_assist_pipeline_id`) to use the configured STT engine |
| `homeassistant_manage_assist_pipeline_tts_engine` | `false` | Update the preferred Assist pipeline (or `homeassistant_assist_pipeline_id`) to use the configured TTS engine |
| `homeassistant_assist_pipeline_id` | `""` | Assist pipeline ID to update; defaults to Home Assistant’s preferred pipeline |
| `homeassistant_assist_pipeline_stt_engine_id` | `""` | Explicit STT entity ID (for example `stt.voxhelm`); leave empty to auto-discover the Wyoming STT entity |
| `homeassistant_assist_pipeline_stt_language` | `""` | STT language to store alongside the engine; defaults to the pipeline’s existing STT language or pipeline language |
| `homeassistant_assist_pipeline_tts_engine_id` | `""` | Explicit TTS entity ID (for example `tts.voxhelm`); leave empty to auto-discover the Wyoming TTS entity |
| `homeassistant_assist_pipeline_tts_language` | `""` | TTS language to store alongside the engine; defaults to the pipeline’s existing TTS language or pipeline language |
| `homeassistant_assist_pipeline_tts_voice` | `""` | Optional TTS voice ID (for example `en_US-lessac-medium`) stored on the Assist pipeline |
| `homeassistant_assist_pipelines` | `[]` | Declarative Assist pipelines managed by name or id, including preferred pipeline selection |
| `homeassistant_area_registry_updates` | `[]` | Area alias and canonical sensor updates applied through Home Assistant’s area registry |
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
        homeassistant_assist_pipelines:
          - name: "Home Assistant"
            language: "en"
            stt_language: "en"
            tts_language: "en"
            tts_voice: "en_US-lessac-medium"
          - name: "Home Assistant DE"
            language: "de"
            stt_language: "de"
            tts_language: "de"
            tts_voice: "de_DE-thorsten-high"
            preferred: true
        homeassistant_area_registry_updates:
          - area_id: "living_room"
            aliases: ["living room"]
            temperature_entity_id: "sensor.wohnzimmer_sensor_temperature"
          - area_id: "wintergarten"
            aliases: ["winter garden"]
            temperature_entity_id: "sensor.sensor_wintergarten_temperature"
```

## Notes

- The role intentionally defaults to non-destructive config management. Set `homeassistant_initial_deploy: true` or combine `homeassistant_manage_*` flags with `homeassistant_overwrite_config: true` for the first automation run, then relax them for day‑2 updates.
- Traefik output must match the legacy file byte-for-byte before production cutover. Keep the middleware list/ordering in sync with your production Traefik configuration.
- The role expects `uv` to be preinstalled (handled elsewhere in ops-library). It will fail fast if the binary is missing.
- The Matter server path is best-effort only: upstream supports HAOS add-ons, and non-HAOS installs are explicitly unsupported.
- Matter/Thread traffic depends on IPv6 link-local multicast and correct Router Advertisement handling on the host network.
- When `homeassistant_manage_matter_integration: true`, the role provisions the Matter config entry via the Home Assistant API using `homeassistant_matter_integration_url`. Otherwise, configure the integration via the UI.
- When `homeassistant_manage_otbr_integration: true`, the role provisions the OTBR config entry via the Home Assistant API using `homeassistant_otbr_integration_url`. Otherwise, configure the integration via the UI.
- When `homeassistant_manage_wyoming_integration: true`, the role provisions the Wyoming config entry via the Home Assistant API using `homeassistant_wyoming_host` and `homeassistant_wyoming_port`.
- When `homeassistant_manage_assist_pipeline_stt_engine: true` and/or `homeassistant_manage_assist_pipeline_tts_engine: true`, the role updates the preferred Assist pipeline (or `homeassistant_assist_pipeline_id`) over the Home Assistant admin WebSocket API so the STT and TTS engines point at the Wyoming entities. By default it auto-discovers both entities from the matching Wyoming config entry.
- When `homeassistant_assist_pipelines` is non-empty, the role creates or updates those pipelines over the Home Assistant admin WebSocket API and can switch the preferred pipeline in the same run. This is the safer option when you want both English and German pipelines available at once.
- When `homeassistant_area_registry_updates` is non-empty, the role updates the matching areas over the Home Assistant admin WebSocket API. This is useful for adding Assist-friendly area aliases such as `living room` for `Wohnzimmer`, and for pinning an area to the preferred temperature sensor when multiple temperature entities exist.
- OTBR provisioning assumes the OTBR REST API is already reachable; the role does not manage OTBR itself.
- The API token must be a long-lived Home Assistant access token with admin permissions; validation fails if it is missing, too short, or a placeholder like `CHANGE_ME`.
- The server does not require a Bluetooth adapter by default because HA uses the Companion app for commissioning.
- When enabling the Matter server, keep Python >= 3.12 and use `python-matter-server[server]` so native dependencies are installed.
