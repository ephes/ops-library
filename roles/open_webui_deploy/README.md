# Open WebUI Deploy Role

Deploys Open WebUI on Ubuntu using Docker Compose and exposes it through Traefik with optional basic auth.

## Quick Start

```yaml
- hosts: macmini
  become: true
  roles:
    - role: local.ops_library.open_webui_deploy
      vars:
        open_webui_ollama_base_url: "http://studio.tailde2ec.ts.net:11434"
        open_webui_traefik_host: "open-webui.home.xn--wersdrfer-47a.de"
        open_webui_basic_auth_user: "admin"
        open_webui_basic_auth_password: "CHANGEME"
```

Note: the inventory host is `macstudio`, but the Tailscale hostname is `studio.tailde2ec.ts.net` (not `macstudio.tailde2ec.ts.net`). Use the `studio` hostname for `open_webui_ollama_base_url`.

## Architecture

- Open WebUI runs as a Docker container managed by a systemd oneshot unit.
- Traefik routes HTTPS traffic to the local container port bound on loopback.
- Persistent state is stored in a host bind mount that maps to `/app/backend/data` inside the container.

## Role Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `open_webui_image` | `ghcr.io/open-webui/open-webui:main` | Docker image tag to deploy. |
| `open_webui_bind_host` | `127.0.0.1` | Host interface used for the container bind. |
| `open_webui_host_port` | `3000` | Host port bound to the container. |
| `open_webui_container_port` | `8080` | Container port for Open WebUI. |
| `open_webui_site_dir` | `/home/openwebui/site` | Directory holding compose + env files. |
| `open_webui_data_dir` | `/mnt/cryptdata/open-webui/data` | Persistent storage mapped to `/app/backend/data`. |
| `open_webui_ollama_base_url` | `http://localhost:11434` | Ollama base URL Open WebUI should use. |
| `open_webui_webui_secret_key` | `""` | Optional `WEBUI_SECRET_KEY` for session signing. |
| `open_webui_webui_auth_enabled` | `true` | Whether to set `WEBUI_AUTH` (disable only for first-time bootstrap). |
| `open_webui_openai_api_key` | `""` | Optional OpenAI API key. |
| `open_webui_openai_api_base_url` | `""` | Optional OpenAI-compatible base URL. |
| `open_webui_extra_env` | `{}` | Extra environment variables to append to `.env`. |
| `open_webui_traefik_enabled` | `true` | Manage Traefik routing. |
| `open_webui_traefik_host` | `""` | Hostname routed via Traefik. |
| `open_webui_basic_auth_enabled` | `true` | Enable basic auth for external access. |
| `open_webui_basic_auth_user` | `admin` | Basic auth username. |
| `open_webui_basic_auth_password` | `""` | Basic auth password (bcrypt hash generated). |
| `open_webui_basic_auth_password_hash` | `""` | Pre-generated bcrypt hash (overrides password). |
| `open_webui_internal_ip_ranges` | RFC1918 + Tailnet ranges | IPs that bypass basic auth. |

## Environment Variables

The role renders an `.env` file with the following Open WebUI settings (if non-empty):

- `OLLAMA_BASE_URL` – base URL for Ollama.
- `WEBUI_AUTH` – set to `false` only for first-time setup (Open WebUI defaults to auth enabled).
- `WEBUI_SECRET_KEY` – optional secret for session signing (recommended for production).
- `OPENAI_API_KEY` – optional OpenAI key for external providers.
- `OPENAI_API_BASE_URL` – optional OpenAI-compatible base URL.

You can provide any additional env vars via `open_webui_extra_env`.

## Storage

Open WebUI stores its persistent data under `/app/backend/data` inside the container. This role maps that path
from `open_webui_data_dir` on the host so upgrades keep user data intact.

## Traefik Routing

Traefik uses a dual-router pattern:
- Internal IPs bypass basic auth.
- External access requires basic auth.

The Traefik dynamic config path defaults to `/etc/traefik/dynamic/open-webui.yml` via `open_webui_traefik_config_path`. In ops-control, the basic auth inputs typically map to `traefik_secrets.basic_auth_user` and `traefik_secrets.basic_auth_password`.

Set `open_webui_traefik_entrypoints`, `open_webui_traefik_middlewares`, and `open_webui_traefik_cert_resolver`
if your Traefik instance needs custom settings.

## Testing

```bash
# Check container status
systemctl status open-webui

# Verify local HTTP response
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
- Check `journalctl -u open-webui -f` for Docker errors.
- Ensure Docker Compose v2 is installed (`docker compose version`).

### Traefik route not responding
- Confirm `/etc/traefik/dynamic/open-webui.yml` exists.
- Restart Traefik (`systemctl restart traefik`).

## Removal

Use the `open_webui_remove` role to stop the service and clean up data when desired.
