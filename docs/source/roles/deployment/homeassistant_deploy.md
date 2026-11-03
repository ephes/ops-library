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
- UniFi password discovery supports file or SOPS-provided secrets; automatic generation is no longer supported.
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
- `homeassistant_unifi_password_source` (`file|variable`) plus supporting vars for secrets discovery.

See `roles/homeassistant_deploy/defaults/main.yml` for the full variable catalog.

## GPS Timeline and Location Timeline Card

Optional and off by default. The recorder's retention (`purge_keep_days`) is
global, so long-term location history lives in the custom integration
[GPS Timeline](https://github.com/iamyacin/gps-timeline) instead (its own
SQLite WAL database `config/gps_timeline/gps_timeline.db`), shown by the
[Location Timeline Card](https://github.com/iamyacin/timeline_card) with
`history_source: gps_timeline`.

| Variable | Default | Description |
|----------|---------|-------------|
| `homeassistant_gps_timeline_enabled` | `false` | Install the pinned GPS Timeline integration |
| `homeassistant_gps_timeline_version` | `0.1.0-beta.3` | Release tag (commit `688f1b094c58c652bc9a49702486cd9d86b05376`) |
| `homeassistant_gps_timeline_sha256` | `feb29bc1…1ee34e` | sha256 of the tag archive; change it together with the version |
| `homeassistant_gps_timeline_download_url` | GitHub tag archive | Download URL of the archive |
| `homeassistant_timeline_card_enabled` | `false` | Install the pinned Location Timeline Card |
| `homeassistant_timeline_card_version` | `1.9.3` | Release of `iamyacin/timeline_card` |
| `homeassistant_timeline_card_sha256` | `d81404bc…987a5` | sha256 of `timeline_card.js` (1,732,646 bytes); change it together with the version |
| `homeassistant_timeline_card_download_url` | GitHub release asset | Download URL of `timeline_card.js` |

- The archive is downloaded to `<site>/downloads/` and checksum-verified before
  it replaces anything. Only `custom_components/gps_timeline` is installed
  (owner `homeassistant_user`, 0755/0644), with the stamp
  `.ops-pinned-version` (`<version> <sha256>`); a matching stamp skips the
  install. ops-deploy's `services.homeassistant` writes the same stamp.
- The card is `config/www/timeline_card.js` (0644) in `www/` (0755), both owned
  by `homeassistant_user`. The file name never changes; the dashboard resource
  is `/local/timeline_card.js?v=<version>`, so an upgrade only bumps `?v=`.
- `restart homeassistant` is notified only when the component or the card
  changed (Home Assistant serves `/local` only when `www/` existed at startup).
- The integration is set up in the UI (config flow, no YAML, no pip
  requirements, Home Assistant 2026.9.0 or newer). The tasks never write
  `configuration.yaml`, `automations.yaml` or `scripts.yaml`, and never delete
  or write `config/gps_timeline`. `homeassistant_backup` and the Echoport
  runner copy its database with `sqlite3 .backup`.
- GitHub tag archives are usually but not guaranteed byte-stable: if the hash
  drifts for the same tag, compare the contents with the tag commit instead of
  loosening the pin.

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

### Wyoming STT/TTS auto-detection

When no explicit engine is supplied, both declarative Assist pipelines and the
standalone STT/TTS update select enabled live `stt.`/`tts.` entities belonging to the
selected Wyoming config entry. The domain separator is matched as a literal dot;
other integrations, config entries and similar prefixes do not qualify. Explicit
engine IDs retain precedence. The YAML folded expressions use one backslash for
the literal dot: doubling it makes Ansible's templating preserve an unwanted
backslash and rejects valid entity IDs. The earlier literal-dot regression
controls remain; live readiness and saved identity are distinguished below.

## Live Assist engine discovery

Automatic STT/TTS selection and standalone STT readiness read the live entity
registry because Home Assistant delays saved-registry updates. Disabled entries
are unavailable. Explicit engine IDs keep precedence. Entry identity retains the
preceding Wyoming flow ID, then the saved config-entry host/port/domain match;
the read-only entry API does not expose endpoint data. Missing both identity
sources fails without guessing. API timeouts and existing readiness retries
remain bounded. Credentials and registry responses remain in protected memory.
Check mode retains its saved-state observation and makes no live discovery call.

Live discovery reuses cached API readiness and the existing configured
retry/delay bounds while waiting for matching enabled entities after startup.
It honors `homeassistant_api_validate_certs`, including the explicit false
setting for an operator-selected HTTPS endpoint. No persistence flush or
fixture delay is used.
