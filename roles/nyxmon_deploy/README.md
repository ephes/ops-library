# Nyxmon Deploy Role

Ansible role for deploying the Nyxmon monitoring service.

## Features

- Supports both rsync (development) and git (production) deployment methods
- Django application configuration and management
- Systemd service management with granian WSGI server
- Traefik reverse proxy configuration
- Telegram monitoring integration
- Automatic migrations and static file collection

## Requirements

- Ubuntu/Debian-based system
- Python 3.8+
- PostgreSQL (if using database)
- Traefik (optional, for reverse proxy)

## Role Variables

### Required Variables

These must be set in your playbook:

```yaml
# Django secret key (generate with: openssl rand -hex 32)
nyxmon_django_secret_key: "your-secret-key"

# Telegram bot credentials for monitoring
nyxmon_telegram_bot_token: "your-bot-token"
nyxmon_telegram_chat_id: "your-chat-id"

# For rsync deployment
nyxmon_source_path: "/path/to/local/nyxmon"  # Required when nyxmon_deploy_method: rsync
```

### Common Configuration

```yaml
# Deployment method
nyxmon_deploy_method: rsync  # or 'git' for production

# Application settings
nyxmon_app_port: 10017
nyxmon_workers: 4

# Django configuration
nyxmon_django_settings_module: "config.settings.production"
nyxmon_django_allowed_hosts: "127.0.0.1,nyxmon.example.com"

# Traefik configuration
nyxmon_traefik_enabled: true
nyxmon_traefik_host: "nyxmon.example.com"
```

## Example Playbook

### Development Deployment (rsync)

```yaml
---
- name: Deploy Nyxmon (Development)
  hosts: dev-server
  become: true

  roles:
    - role: nyxmon_deploy
      vars:
        nyxmon_deploy_method: rsync
        nyxmon_source_path: "/Users/developer/projects/nyxmon"
        nyxmon_django_secret_key: "{{ vault_django_secret_key }}"
        nyxmon_telegram_bot_token: "{{ vault_telegram_token }}"
        nyxmon_telegram_chat_id: "{{ vault_telegram_chat }}"
        nyxmon_django_settings_module: "config.settings.development"
```

### Production Deployment (git)

```yaml
---
- name: Deploy Nyxmon (Production)
  hosts: prod-server
  become: true

  roles:
    - role: nyxmon_deploy
      vars:
        nyxmon_deploy_method: git
        nyxmon_git_repo: "git@github.com:ephes/nyxmon.git"
        nyxmon_git_version: "v1.0.0"  # or main
        nyxmon_django_secret_key: "{{ vault_django_secret_key }}"
        nyxmon_telegram_bot_token: "{{ vault_telegram_token }}"
        nyxmon_telegram_chat_id: "{{ vault_telegram_chat }}"
        nyxmon_traefik_host: "nyxmon.example.com"
```

## Directory Structure

The role creates the following structure on the target system:

```
/opt/apps/nyxmon/
├── site/                 # Application code
│   ├── src/django/      # Django project (rsync method)
│   ├── .venv/           # Python virtual environment
│   └── cache/           # Django cache directory
├── logs/                # Application logs
└── .env                 # Environment variables
```

## Services

The role manages these systemd services:

- `nyxmon.service` - Main Django application (granian WSGI server)
- `nyxmon-monitor.service` - Monitoring service (if enabled)

## Commands

Useful commands for managing the deployed service:

```bash
# Check service status
systemctl status nyxmon

# View logs
journalctl -u nyxmon -f

# Restart service
systemctl restart nyxmon

# Run Django management commands
sudo -u nyxmon /opt/apps/nyxmon/site/.venv/bin/python \
  /opt/apps/nyxmon/site/src/django/manage.py <command>
```

## License

See repository license.

## Author

Infrastructure Team