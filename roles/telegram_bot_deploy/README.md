# telegram_bot_deploy

Deploy a Telegram bot that replies to messages using the Anthropic Messages API.

## Quick Start

```yaml
- hosts: macmini
  become: true
  roles:
    - role: local.ops_library.telegram_bot_deploy
      vars:
        telegram_bot_token: "{{ sops_secrets.telegram_bot_token }}"
        telegram_bot_anthropic_api_key: "{{ sops_secrets.anthropic_api_key }}"
        telegram_bot_allowed_users: "123456789"
```

## Architecture

- **No custom Docker build** — runs on stock `node:22-alpine`
- **Long polling** — no inbound ports or webhooks required (works behind NAT)
- **Single dependency** — [grammY](https://grammy.dev/) handles Telegram Bot API
- **Anthropic API** — raw `fetch()` calls to the Messages API
- **In-memory conversation history** — per-user, capped at 20 turns

```
[Telegram API] <-- long poll --> [node:22-alpine container]
                                      |
                                      +--> fetch() --> [Anthropic API]
```

## Role Variables

### Required

| Variable | Description |
|---|---|
| `telegram_bot_token` | Bot token from @BotFather |
| `telegram_bot_anthropic_api_key` | Anthropic API key |

### AI Configuration

| Variable | Default | Description |
|---|---|---|
| `telegram_bot_anthropic_model` | `claude-sonnet-4-20250514` | Model to use |
| `telegram_bot_system_prompt` | `You are a helpful assistant. Be concise.` | System prompt |
| `telegram_bot_max_tokens` | `1024` | Max response tokens |

### Access Control

| Variable | Default | Description |
|---|---|---|
| `telegram_bot_allowed_users` | `""` (allow all) | Comma-separated Telegram user IDs |

### Identity & Paths

| Variable | Default |
|---|---|
| `telegram_bot_service_name` | `telegram-bot` |
| `telegram_bot_container_name` | `telegram-bot` |
| `telegram_bot_user` | `telegrambot` |
| `telegram_bot_group` | `telegrambot` |
| `telegram_bot_home` | `/home/telegrambot` |
| `telegram_bot_site_dir` | `/home/telegrambot/site` |
| `telegram_bot_data_dir` | `/home/telegrambot/data` |

### Feature Flags

| Variable | Default | Description |
|---|---|---|
| `telegram_bot_install_docker` | `true` | Install Docker via docker_install role |
| `telegram_bot_manage_user` | `true` | Create system user/group |
| `telegram_bot_healthcheck_enabled` | `true` | Run post-deploy health checks |
| `telegram_bot_extra_env` | `{}` | Extra env vars merged into container env |

### Container

| Variable | Default |
|---|---|
| `telegram_bot_image` | `node:22-alpine` |
| `telegram_bot_restart_policy` | `unless-stopped` |

## Bot Commands

| Command | Description |
|---|---|
| `/start` | Welcome message |
| `/new` | Reset conversation history |
| *(any text)* | Send to Anthropic and reply |

## Setup

1. Create a bot via [@BotFather](https://t.me/BotFather) on Telegram
2. Get your Telegram user ID via [@userinfobot](https://t.me/userinfobot)
3. Add secrets to SOPS-encrypted file
4. Deploy: `just deploy-one telegram-bot`

## Post-Deploy Verification

```bash
# Check container status
docker logs telegram-bot --tail 20

# Should show: "Bot @yourbotname started (long polling)"
```

## Handlers

| Handler | Trigger |
|---|---|
| `reload systemd` | systemd unit file changes |
| `restart telegram-bot` | Any config, code, or compose change |
