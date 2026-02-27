# OpenClaw Deploy Role

Deploys the OpenClaw gateway on Ubuntu using Docker Compose and systemd. The gateway supports multiple messaging channels (Telegram, WhatsApp) with AI-powered replies via configured providers (Anthropic/OpenAI/OpenRouter/Ollama).

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
        openclaw_version: "v2026.2.23"
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
- AI replies are handled by the gateway using configured provider APIs — no external scripts needed.
- Optional model policy patching can enforce a default model and ordered fallback chain under `agents.defaults.model`.
- Persistent state (sessions, config) is stored in a bind-mounted directory owned by container uid 1000.
- The container binds to `127.0.0.1:18789` by default, with optional Traefik reverse proxy for external access. When Traefik is enabled, the bind host is validated to be loopback.
- When Traefik is enabled, role-managed config sets `gateway.bind: "lan"` and `gateway.controlUi.allowedOrigins` to `https://<openclaw_traefik_host>` so the host-side reverse proxy can reach the gateway UI safely.
- Role-managed gateway hardening sets explicit `gateway.trustedProxies`, disables `gateway.allowRealIpFallback`, and configures `gateway.auth.rateLimit`.
- Gateway config (`openclaw.json`) is seeded once on first deploy and not overwritten on subsequent runs (use `openclaw_force_config: true` to overwrite). Existing configs are patched to ensure unused plugins (WhatsApp) are explicitly disabled.
- Logs are written to a bind-mounted log directory with automatic logrotate.
- Optional: an authenticated loopback HTTP endpoint (`/.well-known/openclaw-health`) can be enabled for Nyxmon `json-metrics` checks.

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

### Gateway Hardening

| Variable | Default | Description |
|----------|---------|-------------|
| `openclaw_gateway_config_mode` | `0600` | File mode used for `openclaw.json` |
| `openclaw_gateway_trusted_proxies` | `[127.0.0.1, ::1]` | Trusted proxy IP/CIDR list written to `gateway.trustedProxies` |
| `openclaw_gateway_allow_real_ip_fallback` | `false` | Controls `gateway.allowRealIpFallback` |
| `openclaw_gateway_auth_rate_limit_enabled` | `true` | Enable `gateway.auth.rateLimit` patching |
| `openclaw_gateway_auth_rate_limit_max_attempts` | `10` | Failed auth attempts per window |
| `openclaw_gateway_auth_rate_limit_window_ms` | `60000` | Rate-limit window in ms |
| `openclaw_gateway_auth_rate_limit_lockout_ms` | `300000` | Lockout duration in ms after threshold |
| `openclaw_gateway_auth_rate_limit_exempt_loopback` | `true` | Exempt loopback clients from auth rate limiting |

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
| `openclaw_openai_api_key` | `""` | Optional OpenAI API key (`OPENAI_API_KEY`) for provider `openai` |
| `openclaw_openrouter_api_key` | `""` | Optional OpenRouter API key (`OPENROUTER_API_KEY`) for provider `openrouter` |
| `openclaw_ollama_api_key` | `""` | Optional Ollama API key (`OLLAMA_API_KEY`) for provider `ollama`; when `openclaw_ollama_base_url` is set and this is empty, role injects `ollama-local` |
| `openclaw_ollama_base_url` | `""` | Optional Ollama endpoint (`OLLAMA_BASE_URL`); must be reachable from inside the OpenClaw container |
| `openclaw_reply_system_prompt` | `You are a concise assistant.` | System prompt for AI replies |

### Model Routing Policy

| Variable | Default | Description |
|----------|---------|-------------|
| `openclaw_agent_model_primary` | `""` | Optional default model (`provider/model`) patched to `agents.defaults.model.primary` |
| `openclaw_agent_model_fallbacks` | `[]` | Optional ordered fallback list (`provider/model` entries) patched to `agents.defaults.model.fallbacks` |

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

### Nyxmon Metrics Endpoint

| Variable | Default | Description |
|----------|---------|-------------|
| `openclaw_metrics_endpoint_enabled` | `false` | Enable OpenClaw JSON metrics endpoint for Nyxmon |
| `openclaw_metrics_endpoint_bind` | `127.0.0.1` | Bind address for endpoint service |
| `openclaw_metrics_endpoint_port` | `9104` | Endpoint port |
| `openclaw_metrics_endpoint_path` | `/.well-known/openclaw-health` | Endpoint path |
| `openclaw_metrics_endpoint_auth_user` | `CHANGEME` | Basic-auth username (required when enabled) |
| `openclaw_metrics_endpoint_auth_password` | `CHANGEME` | Basic-auth password (required when enabled) |
| `openclaw_metrics_endpoint_timer_interval` | `120` | Collector timer interval in seconds |
| `openclaw_metrics_endpoint_container_name` | `{{ openclaw_container_name }}` | OpenClaw container queried by collector |
| `openclaw_metrics_endpoint_remove_data_on_disable` | `false` | Remove `openclaw_metrics_endpoint_data_dir` when endpoint is disabled |

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

Note: The deploy health check intentionally uses TCP + container state. OpenClaw also serves a control UI over HTTP, but role health checks avoid endpoint/auth coupling.

## Nyxmon Monitoring Integration

When `openclaw_metrics_endpoint_enabled: true`:

- a root collector timer (`openclaw-metrics-collector.timer`) runs `docker exec <container> node dist/index.js ... --json` and writes JSON to:
  - `{{ openclaw_metrics_endpoint_json_path }}`
- an unprivileged HTTP server (`{{ openclaw_metrics_endpoint_service_name }}`) serves the JSON with basic auth at:
  - `http://{{ openclaw_metrics_endpoint_bind }}:{{ openclaw_metrics_endpoint_port }}{{ openclaw_metrics_endpoint_path }}`
- response includes `meta.age_seconds` to detect stale collector output.

Designed for Nyxmon `json-metrics` checks, for example:

- `$.openclaw.collector_ok == true`
- `$.openclaw.health.ok == true`
- `$.openclaw.channels.telegram.running == true`
- `$.meta.age_seconds < 600`

## Weeknotes/Todo Automation

When `openclaw_weeknotes_enabled: true`, the role deploys a weeknotes handler plus command skills (`/todo`, `/note`, `/snooze`) that provide chat-driven todo and journal management. Weeknotes data is stored under a dedicated directory with pre-edit snapshots and an append-only operation log.

Commands: `/todo add`, `/note add`, `/todo list`, `/snooze`. A daily cron reminder summarizes open todos on weekdays (noise-suppressed when empty; can be snoozed per-day with `/snooze`).

### Weeknotes Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `openclaw_weeknotes_enabled` | `false` | Enable weeknotes/todo skill |
| `openclaw_weeknotes_tz` | `Europe/Berlin` | Timezone for the container (`TZ` env var) |
| `openclaw_weeknotes_skill_name` | `weeknotes-md` | Handler directory name under `openclaw_weeknotes_skills_dir` |
| `openclaw_weeknotes_command_skill_names` | `[todo, note, snooze]` | Slash command skill names deployed as `SKILL.md` |
| `openclaw_weeknotes_skills_dir` | `{{ openclaw_data_dir }}/skills` | Host path for custom skills |
| `openclaw_weeknotes_dir` | `{{ openclaw_data_dir }}/weeknotes` | Host path for weeknotes data |
| `openclaw_weeknotes_container_dir` | `/home/node/.openclaw/weeknotes` | Container mount for weeknotes |
| `openclaw_weeknotes_container_skills_dir` | `/home/node/.openclaw/skills` | Container mount for skills |
| `openclaw_weeknotes_backend` | `local` | Storage backend: `local` or `s3` |
| `openclaw_weeknotes_snapshot_max_count` | `200` | Max snapshots retained per file |
| `openclaw_weeknotes_snapshot_max_days` | `14` | Max snapshot age in days |
| `openclaw_weeknotes_lock_timeout` | `5` | File lock timeout in seconds |
| `openclaw_weeknotes_max_payload_length` | `500` | Max payload length for write operations |
| `openclaw_weeknotes_rate_limit_writes` | `10` | Max writes per rate-limit window |
| `openclaw_weeknotes_rate_limit_window_secs` | `600` | Rate-limit window in seconds |
| `openclaw_weeknotes_reminder_cron` | `0 9 * * 1-5` | Cron schedule for daily reminder |
| `openclaw_weeknotes_reminder_command` | `/todo reminder` | System-event text sent by reminder cron job |

### Weeknotes S3 Backend Variables

Used when `openclaw_weeknotes_backend: s3`.

| Variable | Default | Description |
|----------|---------|-------------|
| `openclaw_weeknotes_s3_endpoint` | `""` | S3/MinIO endpoint URL |
| `openclaw_weeknotes_s3_region` | `us-east-1` | S3 region string |
| `openclaw_weeknotes_s3_bucket` | `""` | Bucket name |
| `openclaw_weeknotes_s3_prefix` | `""` | Optional object key prefix |
| `openclaw_weeknotes_s3_access_key` | `""` | Access key for weeknotes service account |
| `openclaw_weeknotes_s3_secret_key` | `""` | Secret key for weeknotes service account |
| `openclaw_weeknotes_s3_note_key_format` | `%Y-%m-%d.md` | `date` format string for note object key |
| `openclaw_weeknotes_s3_todo_list_mode` | `current_note` | Todo-list source mode: `current_note` or `daily_notes` |
| `openclaw_weeknotes_s3_todo_list_key_regex` | `^[0-9]{4}-[0-9]{2}-[0-9]{2}\\.md$` | Regex used in `daily_notes` mode to select note object keys |
| `openclaw_weeknotes_s3_todo_cache_refresh_secs` | `120` | Cache refresh interval for `daily_notes` mode |
| `openclaw_weeknotes_s3_mc_alias` | `weeknotes` | MinIO client alias name used by handler |
| `openclaw_weeknotes_s3_mc_host_path` | `/usr/local/bin/mc` | Host path to MinIO client binary (bind-mounted read-only) |
| `openclaw_weeknotes_s3_mc_container_path` | `/usr/local/bin/mc` | Container path for MinIO client binary |

### Storage Model

- `local` backend: weekly files `YYYY-Www.md` (e.g., `2026-W09.md`)
- `s3` backend: direct object-store reads/writes using `openclaw_weeknotes_s3_note_key_format` (default daily keys like `2026-02-25.md`)
- Pre-edit snapshots: `.snapshots/<file-or-key>.<timestamp>.bak`
- Operation log: `.ops-log.jsonl` (append-only)

## Docker Compose Services

- **openclaw-gateway**: Main gateway service, starts with `docker compose up`
- **openclaw-cli**: CLI utility, available via `docker compose run --rm openclaw-cli <subcommand>` (uses `profiles: [cli]`, does not auto-start, and shares the gateway network namespace so CLI commands can reach `ws://127.0.0.1:18789`)

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
