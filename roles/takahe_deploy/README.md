# Takahe Deploy Role

Deploys Takahe from source with systemd services, an nginx cache/accel proxy, and Traefik routing. The role provisions PostgreSQL via `postgres_install` and supports rsync (dev) or git (staging/production) deployment modes.

## Features

- Installs Takahe in `/home/takahe/site` with a Python virtualenv.
- Creates `.env` using the upstream Takahe settings schema.
- Runs database migrations and `collectstatic`.
- Configures systemd units: `takahe-gunicorn`, `takahe-stator`, `takahe-nginx`.
- Writes Traefik dynamic config to route HTTPS traffic to nginx.

## Requirements

- Ubuntu/Debian host with systemd
- `nginx`, Python 3, and build tooling installed (handled by this role)
- Traefik running when `takahe_traefik_enabled: true`

## Required Variables

```yaml
takahe_domain: "takahe.example.com"
takahe_secret_key: "..."
takahe_postgres_password: "..."
takahe_email_server: "smtp://user:pass@mail.example.com:587?tls=true"
takahe_email_from: "Takahe <noreply@example.com>"
takahe_error_emails:
  - "ops@example.com"
```

Deployment mode:

```yaml
# rsync (local dev)
takahe_source_mode: rsync
takahe_source_path: "/path/to/takahe"

# git (staging/prod)
takahe_source_mode: git
takahe_git_repo: "https://github.com/jointakahe/takahe.git"
takahe_git_ref: "main"
```

## Common Configuration

```yaml
takahe_environment: "staging"
takahe_app_port: 10023
takahe_nginx_port: 10024
takahe_traefik_enabled: true
takahe_traefik_host: "{{ takahe_domain }}"
```

Note: Takahe only accepts `debug`, `development`, `production`, or `test` as its runtime environment. The role maps `takahe_environment: staging` to `production` in the generated `.env`.

See `defaults/main.yml` and `roles/takahe_shared/defaults/main.yml` for the full variable reference.

## Dependencies

- `local.ops_library.takahe_shared`
- `local.ops_library.postgres_install`

## Example Playbook

```yaml
- hosts: takahe
  become: true
  vars:
    takahe_domain: "takahe.staging.example.com"
    takahe_secret_key: "{{ takahe_secret_key }}"
    takahe_postgres_password: "{{ takahe_postgres_password }}"
    takahe_email_server: "smtp://user:pass@mail.example.com:587?tls=true"
    takahe_email_from: "Takahe <noreply@example.com>"
    takahe_error_emails:
      - "ops@example.com"
    takahe_source_mode: git
    takahe_git_repo: "https://github.com/jointakahe/takahe.git"
    takahe_git_ref: "main"
  roles:
    - role: local.ops_library.takahe_deploy
```

## Handlers

- `reload systemd`
- `restart takahe-gunicorn`
- `restart takahe-stator`
- `restart takahe-nginx`
- `reload traefik`

## Testing

```bash
cd /path/to/ops-library
just test-role takahe_deploy
```

## License

MIT
