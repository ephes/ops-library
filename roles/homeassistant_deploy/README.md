# Home Assistant Deploy Role

Ansible role that installs and configures a Home Assistant Core instance on bare metal/VM hosts using `uv` managed Python environments. The role mirrors the previous bespoke playbook but adapts it to the shared `ops-library` conventions (idempotent tasks, guard rails, and Traefik integration).

## Features

- Creates the `homeassistant` unix user, directory layout, and Zigbee/Matter udev rule.
- Provisions a Python 3.13 virtualenv via `uv` and installs the `homeassistant` package (optional force-reinstall flag).
- Templated systemd service and Traefik dynamic configuration (single-router layout matching production).
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
| `homeassistant_traefik_domain` | `home.xn--wersdrfer-47a.de` | Punycode domain for router host |
| `homeassistant_traefik_entrypoints` | `['web-secure']` | EntryPoints injected into the primary router |

See the defaults file for recorder, logger, timezone, and UniFi integration settings.

## Example Usage

```yaml
- hosts: macmini
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
- Traefik output must match the legacy file byte-for-byte before production cutover. Keep the middleware list/ordering in sync with reality on `macmini`.
- The role expects `uv` to be preinstalled (handled elsewhere in ops-library). It will fail fast if the binary is missing.
