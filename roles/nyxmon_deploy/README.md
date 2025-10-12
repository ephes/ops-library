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
- Python 3.13 (role installs/manageable via uv by default)
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

### Traefik Dual Router Authentication

The role implements a dual router pattern for security:

- **Internal router** (priority 120): LAN and Tailscale clients bypass basic auth
  - IP ranges: RFC1918 private networks, Tailscale CGNAT (100.64.0.0/10), Tailscale IPv6 (fd7a::/48)
- **External router** (priority 100): Public internet requires basic auth
  - Uses shared credentials from `secrets/prod/traefik.yml`

This is **mandatory** for public-facing deployments per security policy.

**Configuration:**

```yaml
nyxmon_basic_auth_enabled: true  # Default: true
nyxmon_basic_auth_user: "admin"
nyxmon_basic_auth_password: "{{ traefik_secrets.basic_auth_password }}"  # Plain text, will be hashed
nyxmon_internal_ip_ranges:  # Customize for your network
  - "192.168.0.0/16"
  - "100.64.0.0/10"
  - "YOUR_IPV6_PREFIX::/64"
```

**Note:** The role expects a plain-text password in `nyxmon_basic_auth_password`. It will automatically generate the bcrypt hash using `htpasswd` during deployment. Do NOT provide a pre-hashed password.

**Testing:**
- From LAN (192.168.x): No auth prompt
- From Tailscale (100.x): No auth prompt
- From public internet: Basic auth prompt appears

### Rsync behaviour (default)

By default the role performs a "local source" deployment when `nyxmon_deploy_method: rsync`:

1. Validates that the Nyxmon repository contains `src/django/`, `src/nyxmon/`, `src/nyxboard/`, `pyproject.toml`, and `README.md`.
2. Rsyncs those directories/files to the target host.
3. Runs `uv sync --no-default-groups --no-dev` inside `/home/nyxmon/site`, so Nyxmon is installed directly from the freshly synced sources while only runtime dependencies are resolved from PyPI.

This workflow keeps the server in lockstep with the local checkout and avoids the broken-wheel issue we hit earlier.

#### Configuration knobs

```yaml
# Additional source directories to sync alongside src/django/
nyxmon_rsync_additional_paths:
  - src/nyxmon/
  - src/nyxboard/

# Additional individual files to copy from source (e.g., README.md for package metadata)
nyxmon_rsync_extra_files:
  - README.md

# Use the project's pyproject.toml for dependency resolution (default true)
# Set to false to fall back to the role's template when deploying purely from PyPI
nyxmon_use_source_pyproject: true
```

> **Note:** The role validates that `pyproject.toml`, `src/django/`, and any
> configured `nyxmon_rsync_additional_paths` and `nyxmon_rsync_extra_files` exist
> under `nyxmon_source_path` to avoid accidentally wiping files on the remote host
> when rsync runs with `delete: true`.

### Switching back to PyPI-based deployments

If you prefer the original "install from PyPI" mode (e.g. for production), override these variables:

```yaml
nyxmon_rsync_additional_paths: []
nyxmon_rsync_extra_files: []
nyxmon_use_source_pyproject: false
```

With those settings the role:

- Only rsyncs `src/django/`
- Templates `pyproject.toml` with the PyPI requirement (`nyxmon>=…`)
- Runs `uv sync --upgrade-package nyxmon`, pulling the published wheel instead of using the local sources

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
/home/nyxmon/
├── site/                 # Application code (nyxmon_site_path)
│   ├── src/django/       # Django project (rsync method)
│   ├── src/nyxmon/       # Nyxmon package (rsync defaults)
│   ├── src/nyxboard/     # Nyxboard package (rsync defaults)
│   ├── .venv/            # Default uv virtual environment (nyxmon_venv_path)
│   └── cache/            # Django cache directory
├── logs/                 # Application logs
└── .env                  # Environment variables
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
sudo -u nyxmon /home/nyxmon/site/.venv/bin/python \
  /home/nyxmon/site/src/django/manage.py <command>
```

## License

See repository license.

## Author

Infrastructure Team
