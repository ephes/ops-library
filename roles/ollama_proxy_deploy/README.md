# Ollama Proxy Deploy Role

Deploys a Traefik dynamic configuration that exposes a local Ollama API endpoint over HTTPS with
basic auth and a dual-router pattern (internal bypass + external auth).

## Quick Start

```yaml
- hosts: macmini
  become: true
  vars:
    secrets: "{{ lookup('community.sops.sops', 'secrets/prod/ollama-proxy.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.ollama_proxy_deploy
      vars:
        ollama_proxy_backend_url: "http://127.0.0.1:11434"
        ollama_proxy_traefik_host: "ollama.home.xn--wersdrfer-47a.de"
        ollama_proxy_basic_auth_user: "{{ secrets.basic_auth_user | default('ollama') }}"
        ollama_proxy_basic_auth_password: "{{ secrets.basic_auth_password }}"
```

## Requirements

- Traefik deployed and running on the target host
- `apache2-utils` (for `htpasswd`) on Debian/Ubuntu targets

## Role Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ollama_proxy_traefik_enabled` | `true` | Manage Traefik routing. |
| `ollama_proxy_traefik_host` | `""` | Hostname routed via Traefik (required when enabled). |
| `ollama_proxy_traefik_entrypoints` | `["web-secure"]` | Traefik entrypoints for HTTPS routers. |
| `ollama_proxy_traefik_cert_resolver` | `""` | Cert resolver (empty uses file-provider certs). |
| `ollama_proxy_traefik_config_path` | `/etc/traefik/dynamic/ollama.yml` | Dynamic config path. |
| `ollama_proxy_backend_url` | `http://127.0.0.1:11434` | Backend Ollama URL. |
| `ollama_proxy_basic_auth_enabled` | `true` | Enable basic auth for external access. |
| `ollama_proxy_basic_auth_user` | `ollama` | Basic auth username. |
| `ollama_proxy_basic_auth_password` | `""` | Basic auth password (bcrypt hash generated). |
| `ollama_proxy_basic_auth_password_hash` | `""` | Pre-generated bcrypt hash (overrides password). |
| `ollama_proxy_basic_auth_remove_header` | `true` | Remove `Authorization` header before proxying. |
| `ollama_proxy_internal_ip_ranges` | RFC1918 + Tailnet + IPv6 | IPs that bypass basic auth. |

Note: the default ISP IPv6 prefix in `ollama_proxy_internal_ip_ranges` is homelab-specific; override it in ops-control for other environments.

## Traefik Routing

- Internal IPs (LAN/Tailscale) bypass basic auth.
- External access requires basic auth.
- HTTP requests are redirected to HTTPS.
- Security headers and gzip compression are enabled.

## Testing

```bash
# From public network (should 401 without auth)
curl -I https://ollama.home.xn--wersdrfer-47a.de/v1/models

# With auth (should 200)
curl -I -u user:pass https://ollama.home.xn--wersdrfer-47a.de/v1/models
```

## Troubleshooting

- Verify Traefik config exists: `/etc/traefik/dynamic/ollama.yml`
- Restart Traefik: `systemctl restart traefik`
- Confirm Ollama is reachable from Traefik host:
  `curl -fsS http://127.0.0.1:11434/v1/models`
