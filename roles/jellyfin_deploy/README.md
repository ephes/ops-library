# Jellyfin Deploy Role

Deploys [Jellyfin](https://jellyfin.org/) via the official apt repository as a systemd-managed service (no containers) with Traefik exposure and basic auth in front of Jellyfin's own login.

## Features
- Configures the Jellyfin apt repository and installs `jellyfin` + `jellyfin-ffmpeg` from upstream packages.
- Ensures data/config/log directories exist, along with the media roots under `/mnt/cryptdata/media/video/...`.
- Renders a Traefik dynamic config with HTTPS, HTTP→HTTPS redirect, and optional basic auth.
- Starts/enables the `jellyfin` systemd service and performs a lightweight HTTP health check.

## Requirements
- Debian/Ubuntu host with systemd.
- Traefik file provider mounted at `/etc/traefik/dynamic/` (for exposure).
- `htpasswd` available for basic auth hashing (installed via `apache2-utils`).

## Usage

```yaml
- hosts: media
  become: true
  vars:
    traefik_secrets: "{{ lookup('community.sops.sops', playbook_dir + '/../../secrets/prod/traefik.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.jellyfin_deploy
      vars:
        jellyfin_traefik_host: "media.home.xn--wersdrfer-47a.de"
        jellyfin_media_directories:
          - /mnt/cryptdata/media/video/movies
          - /mnt/cryptdata/media/video/tv
          - /mnt/cryptdata/media/video/youtube
        jellyfin_basic_auth_user: "{{ traefik_secrets.basic_auth_user | default('admin') }}"
        jellyfin_basic_auth_password: "{{ traefik_secrets.basic_auth_password }}"
```

## Key Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `jellyfin_http_port` | `8096` | Jellyfin HTTP port (backend for Traefik). |
| `jellyfin_traefik_host` | `media.example.com` | External hostname routed through Traefik. |
| `jellyfin_media_directories` | `/mnt/cryptdata/media/video/...` | Media library roots to ensure exist/readable. |
| `jellyfin_basic_auth_user` | `jellyfin` | Basic auth username; requires password or hash when enabled. |
| `jellyfin_configure_repo` | `true` | Add the upstream Jellyfin apt repository before installing packages. |
| `jellyfin_healthcheck_enabled` | `true` | Run a simple HTTP health check after starting the service. |
| `jellyfin_internal_ip_ranges` | RFC1918 + Tailscale | Internal allowlist for auth-free router when basic auth is enabled. |
| `jellyfin_media_dir_owner`/`jellyfin_media_dir_group` | `root:root` | Media dirs are created world-readable (0755) for read-only access; override if tighter permissions are needed. |

See `defaults/main.yml` and `roles/jellyfin_shared/defaults/main.yml` for the full variable reference.
