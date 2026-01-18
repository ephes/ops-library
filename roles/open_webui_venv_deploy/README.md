# Open WebUI Venv Deploy Role

Deploys Open WebUI on Ubuntu using a uv-managed virtualenv and systemd, with Traefik routing and optional basic auth.

## Quick Start

```yaml
- hosts: macmini
  become: true
  roles:
    - role: local.ops_library.open_webui_venv_deploy
      vars:
        open_webui_ollama_base_url: "http://studio.tailde2ec.ts.net:11434"
        open_webui_traefik_host: "open-webui.home.xn--wersdrfer-47a.de"
        open_webui_basic_auth_user: "admin"
        open_webui_basic_auth_password: "CHANGEME"
        open_webui_data_dir: "/mnt/cryptdata/open-webui/data"
```

Note: the inventory host is `macstudio`, but the Tailscale hostname is `studio.tailde2ec.ts.net` (not `macstudio.tailde2ec.ts.net`). Use the `studio` hostname for `open_webui_ollama_base_url`.

## Architecture

- Open WebUI runs directly from a uv-managed virtualenv.
- A systemd service executes `open-webui serve` on the configured port.
- `DATA_DIR` is set explicitly to ensure persistent data is stored outside the venv.
- Traefik routes HTTPS traffic to the loopback-bound service with optional basic auth.

## Role Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `open_webui_site_dir` | `/opt/open-webui` | Base directory for the app and venv. |
| `open_webui_data_dir` | `/var/lib/open-webui` | Persistent Open WebUI data directory. |
| `open_webui_log_dir` | `/var/log/open-webui` | Log directory (for future use). |
| `open_webui_env_path` | `{{ open_webui_site_dir }}/open-webui.env` | Environment file path. |
| `open_webui_venv_path` | `{{ open_webui_site_dir }}/.venv` | Virtualenv path. |
| `open_webui_python_version` | `3.11` | Python version installed via uv. |
| `open_webui_package_spec` | `open-webui` | Package spec for uv pip install (e.g., `open-webui==x.y.z`). |
| `open_webui_uv_path` | `/usr/local/bin/uv` | Path to the uv binary. |
| `open_webui_manage_uv` | `true` | Install uv automatically via `uv_install`. |
| `open_webui_bind_host` | `127.0.0.1` | Bind host passed to `open-webui serve` when enabled. |
| `open_webui_host_port` | `3000` | Port for `open-webui serve`. |
| `open_webui_use_host_flag` | `true` | Add `--host {{ open_webui_bind_host }}` to the CLI. Disable if unsupported. |
| `open_webui_extra_args` | `[]` | Additional CLI args passed to `open-webui serve`. |
| `open_webui_ollama_base_url` | `http://localhost:11434` | Ollama base URL Open WebUI should use. |
| `open_webui_webui_secret_key` | `""` | Optional `WEBUI_SECRET_KEY` for session signing. |
| `open_webui_webui_auth_enabled` | `true` | Whether to set `WEBUI_AUTH` (disable only for first-time bootstrap). |
| `open_webui_openai_api_key` | `""` | Optional OpenAI API key. |
| `open_webui_openai_api_base_url` | `""` | Optional OpenAI-compatible base URL. |
| `open_webui_extra_env` | `{}` | Extra environment variables to append to the env file. |
| `open_webui_traefik_enabled` | `true` | Manage Traefik routing. |
| `open_webui_traefik_host` | `""` | Hostname routed via Traefik. |
| `open_webui_basic_auth_enabled` | `true` | Enable basic auth for external access. |
| `open_webui_basic_auth_user` | `admin` | Basic auth username. |
| `open_webui_basic_auth_password` | `""` | Basic auth password (bcrypt hash generated). |
| `open_webui_basic_auth_password_hash` | `""` | Pre-generated bcrypt hash (overrides password). |
| `open_webui_internal_ip_ranges` | RFC1918 + Tailnet ranges | IPs that bypass basic auth. |

## Environment Variables

The role renders an env file with the following Open WebUI settings (if non-empty):

- `OLLAMA_BASE_URL` - base URL for Ollama.
- `WEBUI_AUTH` - set to `false` only for first-time setup (Open WebUI defaults to auth enabled).
- `WEBUI_SECRET_KEY` - optional secret for session signing (recommended for production).
- `OPENAI_API_KEY` - optional OpenAI key for external providers.
- `OPENAI_API_BASE_URL` - optional OpenAI-compatible base URL.

You can provide any additional env vars via `open_webui_extra_env`.

## Storage

Open WebUI stores its persistent data under `DATA_DIR`. This role sets `DATA_DIR={{ open_webui_data_dir }}` so upgrades
keep user data intact.

## Traefik Routing

Traefik uses a dual-router pattern:
- Internal IPs bypass basic auth.
- External access requires basic auth.

The Traefik dynamic config path defaults to `/etc/traefik/dynamic/open-webui.yml` via `open_webui_traefik_config_path`. In ops-control, the basic auth inputs typically map to `traefik_secrets.basic_auth_user` and `traefik_secrets.basic_auth_password`.

Set `open_webui_traefik_entrypoints`, `open_webui_traefik_middlewares`, and `open_webui_traefik_cert_resolver`
if your Traefik instance needs custom settings.

## Testing

```bash
systemctl status open-webui
curl -fsS http://127.0.0.1:3000/
```

## Deploy preflight (ops-control)

The ops-control deploy playbook includes a port-collision preflight. If you intentionally need to bypass it, use:

```bash
SKIP_PREFLIGHT_PORTS=true just deploy-one open_webui
```

Or when calling Ansible directly:

```bash
ansible-playbook -e skip_preflight_ports=true playbooks/deploy-open-webui.yml
```

## Troubleshooting

### Service does not start
- Check `journalctl -u open-webui -f` for errors.
- Ensure `{{ open_webui_venv_path }}/bin/open-webui` exists.
- If the CLI does not support `--host`, set `open_webui_use_host_flag=false`.

### Traefik route not responding
- Confirm `/etc/traefik/dynamic/open-webui.yml` exists.
- Restart Traefik (`systemctl restart traefik`).

## Removal

Use the `open_webui_venv_remove` role to stop the service and clean up data when desired.
