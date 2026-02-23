# OpenClaw Deploy Role

Deploys the OpenClaw gateway on Ubuntu using Docker Compose and systemd. The gateway supports multiple messaging channels (Telegram, WhatsApp) with AI-powered replies via Anthropic.

## Key Difference

Unlike other service roles, OpenClaw has no prebuilt Docker image. This role clones the source repo and runs `docker build` on-host using the upstream Dockerfile. The build is skipped when the image+tag already exists and the source hasn't changed.

## Lifecycle Exception (Backup/Restore)

OpenClaw intentionally does not provide `openclaw_backup` or `openclaw_restore` roles.

- Backup/restore is centralized through Echoport.
- Do not use `just backup openclaw` or `just restore openclaw`.
- Use the operator commands and restore-drill workflow in `ops-control/docs/OPENCLAW_RUNBOOK.md` (private `ops-control` repo).

## Quick Start

```yaml
- hosts: macmini
  become: true
  roles:
    - role: local.ops_library.openclaw_deploy
      vars:
        openclaw_version: "v2026.2.21"
        openclaw_data_dir: "/mnt/cryptdata/openclaw/data"
        openclaw_gateway_token: "{{ sops_secrets.gateway_token }}"
        openclaw_anthropic_api_key: "{{ sops_secrets.anthropic_api_key }}"
        openclaw_telegram_enabled: true
        openclaw_telegram_bot_token: "{{ sops_secrets.telegram_bot_token }}"
        openclaw_telegram_allow_from:
          - 304012876
        openclaw_traefik_enabled: true
        openclaw_traefik_host: "openclaw.macmini.tailde2ec.ts.net"
```

## Architecture

- OpenClaw runs as a Docker container managed by a systemd oneshot unit.
- The source repo is cloned to a build directory and `docker build` creates the image using the upstream Dockerfile. The container uses the upstream `CMD` — no command override in compose.
- The gateway handles all messaging channels internally (Telegram via grammY, etc.).
- AI replies are handled by the gateway using the Anthropic API — no external scripts needed.
- Persistent state (sessions, config) is stored in a bind-mounted directory owned by container uid 1000.
- The container binds to `127.0.0.1:18789` by default, with optional Traefik reverse proxy for external access. When Traefik is enabled, the bind host is validated to be loopback.
- Gateway config (`openclaw.json`) is seeded once on first deploy and not overwritten on subsequent runs (use `openclaw_force_config: true` to overwrite). Existing configs are patched to ensure unused plugins (WhatsApp) are explicitly disabled.
- Logs are written to a bind-mounted log directory with automatic logrotate.

## Role Variables

### Required Variables

| Variable | Description |
|----------|-------------|
| `openclaw_version` | Git tag to checkout and build (e.g. `v2026.2.21`) |
| `openclaw_gateway_token` | Gateway authentication token |
| `openclaw_anthropic_api_key` | Anthropic API key for AI replies |

### Networking

| Variable | Default | Description |
|----------|---------|-------------|
| `openclaw_bind_host` | `127.0.0.1` | Host IP to bind the container port |
| `openclaw_host_port` | `18789` | Host port for the gateway |
| `openclaw_container_port` | `18789` | Container port for the gateway |

### Telegram Channel

| Variable | Default | Description |
|----------|---------|-------------|
| `openclaw_telegram_enabled` | `false` | Enable Telegram channel |
| `openclaw_telegram_bot_token` | `""` | Telegram bot token (required when enabled) |
| `openclaw_telegram_dm_policy` | `allowlist` | DM policy: `allowlist` or `open` |
| `openclaw_telegram_allow_from` | `[]` | Numeric Telegram user IDs for allowlist |

### AI Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `openclaw_reply_system_prompt` | `You are a concise assistant.` | System prompt for AI replies |

### Build Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `openclaw_image_name` | `openclaw` | Docker image name |
| `openclaw_image_tag` | `{{ openclaw_version }}` | Docker image tag |
| `openclaw_force_rebuild` | `false` | Force Docker image rebuild even if image exists |

### Traefik Reverse Proxy

| Variable | Default | Description |
|----------|---------|-------------|
| `openclaw_traefik_enabled` | `false` | Enable Traefik reverse proxy configuration |
| `openclaw_traefik_host` | `""` | Hostname for Traefik router (required when enabled) |
| `openclaw_traefik_config_path` | `/etc/traefik/dynamic/openclaw.yml` | Path for Traefik dynamic config |
| `openclaw_traefik_entrypoints` | `[web-secure]` | Traefik entrypoints to listen on |
| `openclaw_traefik_cert_resolver` | `""` | TLS cert resolver (empty = default TLS) |

### Advanced

| Variable | Default | Description |
|----------|---------|-------------|
| `openclaw_gateway_config` | `{}` | Full config override — rendered directly as `openclaw.json`, ignoring individual channel vars |
| `openclaw_force_config` | `false` | Overwrite `openclaw.json` even if it already exists |
| `openclaw_extra_env` | `{}` | Extra environment variables merged into the container env |
| `openclaw_data_dir` | `/home/openclaw/data` | Persistent data directory (bind-mounted into container) |
| `openclaw_log_dir` | `/home/openclaw/logs` | Log directory (bind-mounted to `/tmp/openclaw` in container) |
| `openclaw_mem_limit` | `2g` | Docker container memory limit |
| `openclaw_cpus` | `1.0` | Docker container CPU limit |
| `openclaw_pids_limit` | `256` | Docker container PID limit |
| `openclaw_node_max_old_space_size` | `1536` | Node.js memory limit (MB) |
| `openclaw_logrotate_days` | `7` | Days to retain rotated log files |

### Feature Flags

| Variable | Default | Description |
|----------|---------|-------------|
| `openclaw_install_docker` | `true` | Install Docker via docker_install role |
| `openclaw_manage_user` | `true` | Create system user/group |
| `openclaw_healthcheck_enabled` | `true` | Run post-deploy health check (TCP + container) |

For a complete list, see `defaults/main.yml`.

## Gateway Configuration

The role seeds `openclaw.json` into the data directory on first deploy. By default, it builds the config from individual `openclaw_telegram_*` variables with explicit plugin control (unused channels like WhatsApp are disabled). Once seeded, the config is not overwritten on subsequent deploys — set `openclaw_force_config: true` to re-render.

To provide a full custom config, set `openclaw_gateway_config`:

```yaml
openclaw_gateway_config:
  channels:
    telegram:
      enabled: true
      dmPolicy: allowlist
      allowFrom: [304012876]
  plugins:
    entries:
      telegram:
        enabled: true
      whatsapp:
        enabled: false
```

## Health Check

The role performs a two-stage health check after deploy:

1. **TCP port check** — `wait_for` on the bound host/port (TCP connect)
2. **Container check** — verifies the Docker container is in running state

Note: The gateway is a WebSocket server and does not serve plain HTTP, so HTTP-level probes are not used.

## Docker Compose Services

- **openclaw-gateway**: Main gateway service, starts with `docker compose up`
- **openclaw-cli**: CLI utility, available via `docker compose run --rm openclaw-cli <subcommand>` (uses `profiles: [cli]`, does not auto-start)

## Post-Deploy: Telegram

If using `allowlist` dm_policy with `allowFrom`, messages from listed users should work immediately. If pairing is needed:

```bash
docker compose -f /home/openclaw/site/docker-compose.yml \
  run --rm openclaw-cli pairing list telegram
docker compose -f /home/openclaw/site/docker-compose.yml \
  run --rm openclaw-cli pairing approve telegram <CODE>
```

## Handlers

- `reload systemd` — Daemon reload after unit file changes
- `restart openclaw` — Restart the systemd service
- `reload traefik` — Restart Traefik after config changes

## Testing

```bash
# Check container status
systemctl status openclaw
docker compose -f /home/openclaw/site/docker-compose.yml ps

# View logs
docker logs openclaw-gateway --tail 50
docker compose -f /home/openclaw/site/docker-compose.yml logs -f

# CLI access
docker compose -f /home/openclaw/site/docker-compose.yml run --rm openclaw-cli <subcommand>

# Verify Traefik routing (from Tailscale device)
curl -k https://openclaw.macmini.tailde2ec.ts.net/
```

## License

MIT
