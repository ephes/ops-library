# MeTube Deploy Role

Deploys the MeTube yt-dlp web UI from source with uv (Python `metube_python_version`, default 3.14), builds the Angular frontend, renders systemd/Traefik configs, and exposes it at `https://{{ metube_traefik_host }}` with LAN/Tailscale bypass + basic auth for public IPs.

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
| `metube_nodejs_version` | `24` | Node.js major version installed from NodeSource for Angular build. |
| `metube_nodejs_min_version` | `24.15.0` | Oldest Node.js release accepted for the UI build; an older release of the same major is upgraded from NodeSource. Empty disables the check. |
| `metube_ui_build` | `true` | Build the Angular UI (see below). |
| `metube_ui_build_root` | `/var/cache/metube` | UI staging checkout and corepack/pnpm/npm caches (`HOME` of the build). |
| `metube_ui_build_dir` | `{{ metube_ui_build_root }}/src` | Staging checkout the UI is built in. |

Outputs:
- Systemd unit `metube.service` bound to `{{ metube_host }}:{{ metube_port }}` (default 127.0.0.1:8081)
- Traefik dynamic config at `{{ metube_traefik_config_path }}` with internal IP bypass + basic auth externally
- Environment file at `{{ metube_env_file }}` with yt-dlp options, download paths, and concurrency limits

## UI build

The UI is built in a staging checkout (`metube_ui_build_dir`) before
`metube_install_dir` changes:

1. Check out `metube_repo_version` into the staging checkout.
2. If `ui/pnpm-lock.yaml` exists, run `corepack pnpm install --frozen-lockfile`
   and `corepack pnpm run build --configuration <metube_ui_build_configuration>`;
   corepack uses the pnpm version from the `packageManager` field of
   `ui/package.json`. Otherwise run `npm ci` and `npm run build`.
3. Check `ui/dist/metube/browser/index.html` (the path MeTube serves) and
   record the built commit in `ui/dist/metube/.metube-ui-rev`.
4. Check out that exact commit into `metube_install_dir` and swap the build
   into `ui/dist/metube` there.

If dependency install or build fails, the play stops before step 4:
`metube_install_dir` and the running service stay unchanged, and the error
names the failed step. Fix the build or pin `metube_repo_version` and re-run.
The build is skipped when the staged build already matches the commit.

The build needs Node.js `metube_nodejs_version`.x at least
`metube_nodejs_min_version` (Angular CLI 22 refuses Node.js 24 older than
24.15.0). The role writes `/etc/apt/sources.list.d/nodesource-metube.list` for
that major and upgrades an older install of the same major.

Python dependencies are still installed with `uv sync --frozen --no-dev` from
upstream's `uv.lock` (yt-dlp's `deno` extra comes from PyPI that way).

## Optional systemd hardening

`metube_systemd_hardening` defaults to `false`, preserving the existing unit.
Set it to `true` to enable `NoNewPrivileges=true`, `PrivateTmp=true`,
`ProtectSystem=strict`, and `ProtectHome=false`. Writable paths are limited to
`metube_home`, `metube_download_dir`, `metube_temp_dir`, `metube_state_dir`, `metube_audio_download_dir`.
Validate custom paths and application writes on a staging host before enabling.
Enabling or disabling rewrites the unit on the next deploy.

With hardening disabled, existing unit rendering is preserved. Setting both
`metube_systemd_tasks_max` and `metube_systemd_memory_max` currently joins the
settings on one line; correcting that existing behavior is a separate follow-up.
