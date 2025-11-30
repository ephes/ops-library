# Navidrome Deploy Role

Deploys [Navidrome](https://www.navidrome.org/) as a systemd-managed service (no containers) with reverse-proxy exposure via Traefik and optional scheduled rescans.

## Features
- Installs pinned Navidrome release tarball to `{{ navidrome_install_dir }}` with optional `/usr/local/bin` symlink.
- Creates dedicated `navidrome` system user, data/cache/log directories, and renders `/etc/navidrome.toml`.
- Ships hardened systemd unit with configurable limits and optional `navidrome-rescan.timer` for periodic scans.
- Generates Traefik dynamic config (dual-router pattern with internal allow list + basic auth).

## Requirements
- Debian/Ubuntu host with systemd.
- Traefik file provider mounted at `/etc/traefik/dynamic/` (for exposure).
- `htpasswd` available (role installs `apache2-utils`).

## Usage

```yaml
- hosts: media
  become: true
  roles:
    - role: local.ops_library.navidrome_deploy
      vars:
        navidrome_external_url: "https://music.example.com"
        navidrome_traefik_host: "music.example.com"
        navidrome_music_folder: "/mnt/cryptdata/media/music"
        navidrome_basic_auth_user: "admin"
        navidrome_basic_auth_password: "{{ vault_traefik_basic_auth_password }}"
        navidrome_scan_schedule: "@every 6h"
        navidrome_rescan_timer_enabled: false
```

## Key Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `navidrome_version` | `0.58.5` | Navidrome release to install (pinned). |
| `navidrome_download_arch` | auto | Architecture suffix (`amd64`/`arm64`), derived from `ansible_architecture`. |
| `navidrome_download_checksum` | per-arch | SHA256 for the selected tarball; override when bumping versions. |
| `navidrome_music_folder` | `/mnt/cryptdata/media/music` | Path to music library (read-only). |
| `navidrome_data_dir` | `/var/lib/navidrome` | Data/config/cache directory for Navidrome. |
| `navidrome_external_url` | `https://music.example.com` | External base URL (used by Subsonic clients and redirects). |
| `navidrome_scan_schedule` | `@every 6h` | Built-in scanner schedule (`Scanner.Schedule`). |
| `navidrome_rescan_timer_enabled` | `false` | Install a systemd timer calling `navidrome scan`; `navidrome_rescan_full` forces full scans. |
| `navidrome_traefik_enabled` | `true` | Render Traefik dynamic config with dual-router basic auth. |
| `navidrome_basic_auth_user` | `navidrome` | Basic auth username; requires either `navidrome_basic_auth_password` or `_password_hash` when enabled. |

See `defaults/main.yml` and `roles/navidrome_shared/defaults/main.yml` for the full variable reference.
