# opsgate_ingress_deploy

Expose OpsGate over private HTTPS through Traefik on the edge host while proxying to the
macOS backend on `macstudio`.

## What this role does

- writes a Traefik dynamic config for the OpsGate domain
- terminates TLS on the Traefik host
- forwards requests to the configured backend URL
- restricts routing to the configured Tailscale client IP ranges

## Quick Start

```yaml
- hosts: macmini
  become: true
  roles:
    - role: local.ops_library.opsgate_ingress_deploy
      vars:
        opsgate_ingress_backend_url: "http://studio.tailde2ec.ts.net:8711"
        opsgate_ingress_traefik_host: "opsgate.home.xn--wersdrfer-47a.de"
```

## Requirements

- Traefik must already be deployed and running on the target host.
- The target host must be able to reach the OpsGate backend URL over Tailscale or LAN.

## Key Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `opsgate_ingress_traefik_enabled` | `true` | Manage Traefik routing. |
| `opsgate_ingress_traefik_host` | `""` | HTTPS hostname for OpsGate. |
| `opsgate_ingress_traefik_entrypoints` | `["web-secure"]` | HTTPS entrypoints. |
| `opsgate_ingress_traefik_cert_resolver` | `""` | Optional Traefik cert resolver. |
| `opsgate_ingress_traefik_config_path` | `/etc/traefik/dynamic/opsgate.yml` | Dynamic config path. |
| `opsgate_ingress_backend_url` | `""` | Backend OpsGate URL, typically `http://studio.tailde2ec.ts.net:8711`. |
| `opsgate_ingress_allowed_ip_ranges` | Tailscale IPv4/IPv6 | Client IPs allowed to match the router. |

## Routing Model

- HTTPS traffic terminates on Traefik.
- HTTP traffic redirects to HTTPS.
- Only clients from the configured allowed IP ranges match the router.
- Public internet traffic receives no matching route.

## Verification

```bash
curl -kI https://opsgate.home.xn--wersdrfer-47a.de
```
