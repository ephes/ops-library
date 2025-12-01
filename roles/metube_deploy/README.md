# MeTube Deploy Role

Deploys the MeTube yt-dlp web UI from source with uv (Python 3.13), builds the Angular frontend, renders systemd/Traefik configs, and exposes it at `https://{{ metube_traefik_host }}` with LAN/Tailscale bypass + basic auth for public IPs.

Key defaults:

| Variable | Default | Description |
| --- | --- | --- |
| `metube_install_dir` | `/opt/metube` | Source checkout + working directory (contains `app/` and `ui/`). |
| `metube_venv_path` | `/opt/metube/venv` | uv virtualenv target. |
| `metube_download_dir` | `/mnt/cryptdata/media/video/youtube` | Destination for downloads. |
| `metube_state_dir` | `/var/lib/metube` | Persistent state (queue/history). |
| `metube_traefik_host` | `metube.example.com` | Public hostname. |
| `metube_internal_ip_ranges` | RFC1918 + Tailnet | IPs allowed to bypass basic auth. |
| `metube_basic_auth_user` | `metube` | Basic auth user (hash or password required). |
| `metube_manage_uv` | `true` | Install uv automatically via `uv_install`. |
| `metube_python_version` | `3.14` | Python version requested from uv. |
| `metube_nodejs_version` | `20` | Node.js major version installed from NodeSource for Angular build. |

Outputs:
- Systemd unit `metube.service` bound to `{{ metube_host }}:{{ metube_port }}` (default 127.0.0.1:8081)
- Traefik dynamic config at `{{ metube_traefik_config_path }}` with internal IP bypass + basic auth externally
- Environment file at `{{ metube_env_file }}` with yt-dlp options, download paths, and concurrency limits
