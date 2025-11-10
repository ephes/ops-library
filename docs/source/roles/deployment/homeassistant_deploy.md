# Home Assistant Deploy

Deploys Home Assistant Core on bare metal/VM hosts using `uv`-managed Python environments, systemd, and Traefik. The role consolidates the legacy in-repo automation into ops-library while adding guard rails for UI-managed configuration.

## Features

- Creates the `homeassistant` user, directory tree, Zigbee/Matter udev rule, and uv virtualenv.
- Installs Home Assistant via `uv pip` with optional version pinning (`homeassistant_package_spec`).
- Templates systemd/Traefik files and manages handlers for reloads/restarts.
- Optional management of `configuration.yaml`, `secrets.yaml`, and include files with overwrite guards.
- UniFi password discovery supports file, generated, or SOPS-provided secrets.
- Traefik template reproduces the single-router production config (punycode domain, websocket middleware).

## Key Variables

- `homeassistant_manage_configuration` / `homeassistant_overwrite_config` – control templating of `configuration.yaml`.
- `homeassistant_manage_includes` – manage include files like `automations.yaml`.
- `homeassistant_package_spec` – pip spec (e.g. `homeassistant==2025.1.0`).
- `homeassistant_manage_uv` – run the shared `uv_install` helper before provisioning Python (keeps `/usr/local/bin/uv` current).
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
