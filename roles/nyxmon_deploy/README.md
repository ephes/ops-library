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

### Optional OpsGate Producer Integration (Phase 4A)

Set these only when Nyxmon should create OpsGate tickets directly:

```yaml
nyxmon_opsgate_submit_base_url: "http://studio.tailde2ec.ts.net:8711"
nyxmon_opsgate_submit_token: "{{ opsgate_secrets.submit_token_nyxmon }}"
nyxmon_opsgate_approval_base_url: "https://opsgate.home.xn--wersdrfer-47a.de"
```

The submit URL may stay on the direct internal OpsGate API endpoint, but the
approval URL should point at the operator-facing ingress. The role restarts both
`nyxmon.service` and `nyxmon-monitor.service` when `.env` changes so the
long-running alert worker does not keep stale OpsGate link settings.

When monitoring and OpsGate ticket creation are both enabled, the role also runs
a post-deploy smoke check that:

- asserts the rendered `.env` contains the expected submit and approval URLs
- reads the live `nyxmon-monitor.service` process env from `/proc/<pid>/environ`

The deploy fails if the running worker still holds stale OpsGate URL values, so a
regression back to the direct Studio/Tailscale approval link is caught during
deployment validation instead of after an alert fires.

The monitoring worker unit name defaults to `nyxmon-monitor` and can be
overridden with `nyxmon_monitoring_service_name` if a host needs a different
systemd unit name.

### Monitoring reliability and alert policy

Monitoring reliability defaults are rendered into the shared `.env`:

| Variable | Default | Rendered as | Meaning |
| --- | --- | --- | --- |
| `nyxmon_notify_consecutive_failures` | `2` | `NYXMON_NOTIFY_CONSECUTIVE_FAILURES` | Consecutive non-OK samples before the first alert (1..100) |
| `nyxmon_notify_repeat_interval_seconds` | `21600` | `NYXMON_NOTIFY_REPEAT_INTERVAL_SECONDS` | Elapsed time between reminders for an open **error** incident (60..2592000) |
| `nyxmon_notify_warning_repeat_interval_seconds` | `86400` | `NYXMON_NOTIFY_WARNING_REPEAT_INTERVAL_SECONDS` | Elapsed time between reminders for an open **warning** incident (60..2592000) |
| `nyxmon_processing_lease_seconds` | `900` | `NYXMON_PROCESSING_LEASE_SECONDS` | Processing lease before a claimed check is reclaimed |
| `nyxmon_check_batch_size` | `5` | `NYXMON_CHECK_BATCH_SIZE` | Maximum checks claimed per collector iteration (1..100) |

Nyxmon sends the initial alert when the consecutive-failure threshold is met,
then reminds on **elapsed time**, not on a sample count. Reminder cadence is
therefore the same wall-clock interval for a five-minute check and an hourly
one. A check that needs to page on its very first failing sample gets a
per-check policy override in Nyxmon rather than a lower global threshold.

Checks left in `processing` beyond the lease are reclaimed by the worker and
rescheduled. Keep the lease comfortably above the longest valid executor
runtime; the role requires at least five minutes plus one minute per claimed
check. Claims and stale recoveries are processed in bounded batches. The default
of five adds five minutes of result-handling time to the collector deadline. The
configured lease separately includes a five-minute execution floor plus at
least one minute per claimed check, protecting valid in-flight work across a
service restart. Increase the lease with the batch size when the corresponding
throughput gain is worth a longer batch deadline.

All five settings are validated before anything is written: each must be a whole
number, and each is range-checked. A typo fails the deploy instead of landing in
the worker environment.

#### Removed: `nyxmon_notify_repeat_failures`

Reminders used to be counted in samples (`NYXMON_NOTIFY_REPEAT_FAILURES`). That
made the reminder cadence depend on the check interval — twelve samples is
roughly hourly for a five-minute check and roughly twelve-hourly for an hourly
one — so a sample count cannot be translated into a duration without
re-importing the defect. The variable is therefore **ignored, not converted**,
and the env var is no longer rendered.

Setting it is not a hard error. The role logs a deprecation notice naming both
replacements and continues, so an inventory can be migrated without a failed
deploy:

```yaml
# before
nyxmon_notify_consecutive_failures: 1
nyxmon_notify_repeat_failures: 12

# after
nyxmon_notify_consecutive_failures: 2
nyxmon_notify_repeat_interval_seconds: 21600
nyxmon_notify_warning_repeat_interval_seconds: 86400
```

### Database and source-sync safety

The SQLite database stays where Django puts it, inside the deployed tree. The
source sync is what has to be careful about it:

- Both `ansible.posix.synchronize` tasks pass `owner: false` / `group: false`.
  `synchronize` defaults to `archive: true`, which implies `-o -g` and stamps the
  **controller's** uid/gid onto the destination directory. That takes write
  access to the site directory away from the service user mid-sync, and because
  SQLite must create a journal file in that directory it surfaces as
  `attempt to write a readonly database` (`SQLITE_READONLY_DIRECTORY`).
- `nyxmon_rsync_excludes` covers `db.sqlite3` **and** its `-wal`, `-shm` and
  `-journal` sidecars, plus `.env`. Excluding only `db.sqlite3` is not enough:
  `rsync --delete` would remove a live journal sidecar out from under the writer.
- The role reconciles the database and existing sidecars to mode `0600` by
  default. Dedicated systemd drop-ins set `UMask=0077`; when those drop-ins
  change, both writers restart independently of the general restart preference.
  A final post-restart pass verifies that new and existing sidecars cannot expose
  JSON-check credentials to other local accounts.

| Variable | Default | Description |
| --- | --- | --- |
| `nyxmon_rsync_excludes` | database, sidecars, `.env`, caches, VCS dirs | Never copied or deleted by the source sync. |
| `nyxmon_rsync_django_excludes` | `src/`, `media/`, `staticfiles/` | Additional excludes for the Django sync only. |

> Relocating the database onto a dedicated persistent path (e.g. `/var/lib/nyxmon`)
> is tracked as separate work. It is deliberately **not** part of this change:
> it carries its own migration, rollback and divergence-guard semantics that
> warrant review on their own.

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

The sync runs with `owner: false` and `group: false`. rsync's archive defaults
would otherwise stamp the controller's uid/gid onto the destination directory
itself, taking write access to the site directory away from the service user
for the rest of the deploy. Ownership is fixed afterwards by a single recursive
task. That is safe for a different reason than it may look: the database is
inside the tree, but the task only sets owner/group to the service user the
file already belongs to, and never touches modes.

Exclusions are configurable and default to persistent runtime data:

```yaml
nyxmon_rsync_excludes:  # applied to every sync
  - ".env"
  - "db.sqlite3"
  - "db.sqlite3-wal"
  - "db.sqlite3-shm"
  - "db.sqlite3-journal"
  - "db.sqlite3*"
  - "*.sqlite3"
  # ... plus the usual build/VCS noise
nyxmon_rsync_django_excludes:  # applied only to the Django source sync
  - "src/"
  - "media/"
  - "staticfiles/"
```

Every SQLite sidecar is excluded by name: `rsync --delete` removing a live
`-journal` or `-wal` file out from under a running writer costs crash
atomicity, which is worse than a failed write.

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
│   ├── cache/            # Django cache directory
│   └── .env              # Environment variables
└── logs/                 # Application logs
```

The SQLite database lives in the Django directory alongside the code and is
protected from the source sync by `nyxmon_rsync_excludes` - see
[Database and source-sync safety](#database-and-source-sync-safety).

## Services

The role manages these systemd services:

- `nyxmon.service` - Main Django application (granian WSGI server)
- `nyxmon-monitor.service` - Monitoring service (if enabled; configurable via `nyxmon_monitoring_service_name`)

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

## Contributor Notes

The deploy helper extraction keeps the public role entrypoint unchanged while
moving the duplicated systemd and Traefik plumbing into the internal helper
role `local.ops_library.webapp_deploy_internal`. Nyxmon still owns its
role-specific validation, source deployment, Django setup, handlers, and
monitoring tasks. The remaining `user.yml`, `source_*`, and `python.yml` steps
stay in this public role because the comparison with `fastdeploy_deploy`
showed meaningful divergence in ownership, deployment transport, and runtime
orchestration.

## License

See repository license.

## Author

Infrastructure Team
