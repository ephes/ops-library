# LiveKit Deploy Role

Deploys a self-hosted LiveKit stack (livekit-server + Egress) on Ubuntu using Docker Compose and systemd. Intended for the Recorder product's live call handling and subordinate Egress fallback recording. Both services use `network_mode: host` so they can reach the host-local Redis (127.0.0.1:6379) and MinIO (127.0.0.1:9001), and so WebRTC media flows reach the NIC directly without NAT.

## Quick Start

```yaml
- hosts: macmini
  become: true
  roles:
    - role: local.ops_library.livekit_deploy
      vars:
        livekit_node_ip: "192.168.178.94"
        livekit_api_key: "{{ sops_secrets.livekit_api_key }}"
        livekit_api_secret: "{{ sops_secrets.livekit_api_secret }}"
        livekit_s3_access_key: "{{ sops_secrets.livekit_s3_access_key }}"
        livekit_s3_secret_key: "{{ sops_secrets.livekit_s3_secret_key }}"
        livekit_traefik_host: "livekit.home.xn--wersdrfer-47a.de"
```

## Architecture

- livekit-server and livekit-egress run as Docker containers managed by a systemd oneshot unit.
- Both services bind to `network_mode: host` — required for WebRTC UDP/TCP media ports and for reaching host-local Redis and MinIO without port-mapping.
- Config files (`livekit.yaml`, `egress.yaml`) are rendered from Ansible templates into `{{ livekit_config_dir }}` (default `/etc/livekit`) and bind-mounted read-only into each container.
- The LiveKit HTTP/signalling port (default 7880) is proxied by Traefik for external access. WebSocket upgrades are handled transparently.
- Egress records to an S3-compatible bucket (MinIO by default at 127.0.0.1:9001).

## Role Variables

### Required Variables

| Variable | Description |
|----------|-------------|
| `livekit_api_key` | LiveKit API key |
| `livekit_api_secret` | LiveKit API secret |
| `livekit_node_ip` | Host LAN IP for WebRTC ICE candidates (e.g. `192.168.178.94`) |
| `livekit_s3_access_key` | S3/MinIO access key for egress recordings |
| `livekit_s3_secret_key` | S3/MinIO secret key for egress recordings |

### Images

| Variable | Default | Description |
|----------|---------|-------------|
| `livekit_server_image` | `livekit/livekit-server` | LiveKit server image |
| `livekit_server_tag` | `v1.8.0` | LiveKit server image tag |
| `livekit_egress_image` | `livekit/egress` | LiveKit egress image |
| `livekit_egress_tag` | `v1.8.4` | LiveKit egress image tag |

### Directories

| Variable | Default | Description |
|----------|---------|-------------|
| `livekit_site_dir` | `/opt/livekit` | Site directory for Docker Compose file |
| `livekit_config_dir` | `/etc/livekit` | Directory for rendered config files |

### Networking

| Variable | Default | Description |
|----------|---------|-------------|
| `livekit_http_port` | `7880` | LiveKit HTTP/signalling port |
| `livekit_rtc_tcp_port` | `7881` | RTC TCP port |
| `livekit_rtc_port_range_start` | `50000` | Start of UDP media port range |
| `livekit_rtc_port_range_end` | `50100` | End of UDP media port range |
| `livekit_node_ip` | `""` | Host LAN IP written to `rtc.node_ip` (REQUIRED) |

### LiveKit Config

| Variable | Default | Description |
|----------|---------|-------------|
| `livekit_api_key` | `""` | API key written to `keys:` map and webhook (REQUIRED) |
| `livekit_api_secret` | `""` | API secret written to `keys:` map and egress config (REQUIRED) |
| `livekit_webhook_url` | `https://recorder.home.xn--wersdrfer-47a.de/api/livekit/webhook` | Webhook URL for LiveKit events |

### S3 / Egress Storage

| Variable | Default | Description |
|----------|---------|-------------|
| `livekit_s3_access_key` | `""` | S3 access key (REQUIRED) |
| `livekit_s3_secret_key` | `""` | S3 secret key (REQUIRED) |
| `livekit_s3_endpoint` | `http://127.0.0.1:9001` | S3-compatible endpoint |
| `livekit_s3_bucket` | `recorder` | Target bucket for recordings |

### Traefik Reverse Proxy

| Variable | Default | Description |
|----------|---------|-------------|
| `livekit_traefik_enabled` | `true` | Enable Traefik dynamic config rendering |
| `livekit_traefik_host` | `livekit.home.xn--wersdrfer-47a.de` | Hostname for Traefik router (REQUIRED when enabled) |
| `livekit_traefik_config_path` | `/etc/traefik/dynamic/livekit.yml` | Path for Traefik dynamic config |

### Feature Flags

| Variable | Default | Description |
|----------|---------|-------------|
| `livekit_healthcheck_enabled` | `true` | Run post-deploy health check |
| `livekit_healthcheck_timeout` | `60` | Seconds to wait for port to open |
| `livekit_healthcheck_delay` | `3` | Initial delay before health check |

## Handlers

- `reload systemd` — Daemon reload after unit file changes
- `restart livekit` — Restart the systemd service (brings down and up both containers)
- `reload traefik` — Restart Traefik after config changes

## Docker Compose Services

- **livekit-server**: LiveKit signalling server. Listens on port 7880 (HTTP/WS), 7881 (RTC TCP), and UDP range 50000–50100 for media.
- **livekit-egress**: Egress service using Chrome headless for composite recording/streaming. Requires `SYS_ADMIN` cap and large `/dev/shm` (1 GB) for Chrome.

## Health Check

1. **TCP port check** — `wait_for` on port 7880 (TCP connect)
2. **HTTP check** — `uri` GET `http://127.0.0.1:7880/` expecting HTTP 200

## Firewall Notes

Ensure the following ports are accessible from the LAN / recording clients:

- `7880/tcp` — HTTP/WebSocket signalling (also proxied by Traefik)
- `7881/tcp` — RTC TCP fallback
- `50000–50100/udp` — WebRTC media (UDP)

## Post-Deploy Verification

```bash
# Check service status
systemctl status livekit
docker compose -f /opt/livekit/docker-compose.yml ps

# View logs
docker logs livekit-server --tail 50
docker logs livekit-egress --tail 50

# Verify LiveKit responds
curl http://127.0.0.1:7880/
```

## License

MIT
