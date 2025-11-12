# UniFi Deploy Role

Installs the UniFi Network Application on the macmini controller (or any Debian/Ubuntu host) using the shared `ops-library` conventions. The role absorbs the bespoke `infrastructure/services/unifi` playbook: MongoDB provisioning, Java runtime install, UniFi package download, Traefik wiring, Home Assistant read-only user, and firewall management all live behind a single reusable interface.

## Features

- Installs MongoDB 8.0 from the upstream repo, enables authentication, configures quiet logging, logrotate, and an optional cron-based log monitor.
- Creates the `unifi` unix user, directory layout, cache path, and version-pinned UniFi `.deb` download/install logic.
- Ships a hardened custom systemd service that injects Mongo URI + JVM tuning via environment variables to avoid `system.properties` corruption.
- Emits a Traefik dynamic configuration file (and optional static entrypoint tweak) that matches the production router/service layout.
- Opens the canonical UniFi ports with `ufw` and optionally seeds a read-only Home Assistant account inside Mongo/UniFi.

## Key Variables

All tunables live in `defaults/main.yml`. The highlights:

| Variable | Default | Description |
| --- | --- | --- |
| `unifi_mongodb_password` | **(required)** | MongoDB SCRAM password used for the admin + UniFi databases (store with SOPS/Vault). |
| `unifi_deb_url` | `https://dl.ui.com/.../unifi_sysvinit_all.deb` | URL for the UniFi package. Keep in sync with `unifi_version`. |
| `unifi_deb_checksum` | `""` | Optional checksum (sha256:xxxx). Set to enforce artifact integrity. |
| `unifi_jvm_min_heap_mb` / `unifi_jvm_max_heap_mb` | `1024 / 2048` | Heap sizes used in the systemd service. |
| `unifi_external_domain` | `home.xn--wersdrfer-47a.de` | External domain used in the Traefik router + debug output. |
| `unifi_traefik_enabled` | `true` | Toggle Traefik dynamic file management. |
| `unifi_manage_firewall` | `true` | When true, open the standard UniFi TCP/UDP ports via `ufw`. |
| `unifi_create_homeassistant_user` | `false` | Generate + seed a read-only UniFi admin for Home Assistant integration. |
| `unifi_homeassistant_password` | `""` | Optional pre-defined HA password. Leave empty to auto-generate and store under `unifi_homeassistant_password_store`. |
| `unifi_mongodb_repo_distribution_override` | `""` | Force the MongoDB apt codename (defaults to detected release, fallback `noble` if unsupported). |

Review the defaults file for Traefik entrypoints, MongoDB repo release, logrotate script paths, and controller URLs.

## Example Usage

```yaml
- hosts: macmini
  become: true
  roles:
    - role: local.ops_library.unifi_deploy
      vars:
        unifi_mongodb_password: "{{ sops_unifi_mongodb_password }}"
        unifi_external_domain: "home.wersdoerfer.de"
        unifi_traefik_entrypoints: ["web-secure"]
        unifi_create_homeassistant_user: true
        unifi_homeassistant_password: "{{ sops_homeassistant_unifi_password }}"
```

## Notes

- The role assumes Debian/Ubuntu + systemd. It performs a hard fail on other platforms to avoid half-configured hosts.
- MongoDB authentication is mandatory: define `unifi_mongodb_password` via SOPS/Ansible Vault before running the role.
- If you already manage Traefik entrypoints elsewhere, keep `unifi_traefik_manage_api_entrypoint: false` to avoid editing `traefik.toml`.
- For production cutovers, run `unifi_backup` prior to `unifi_deploy` and keep `unifi_remove` ready for clean rollbacks.
