# Python App Systemd Role

Deploy Python applications with systemd service management.

## Features

- **Working tree deployment**: Deploy directly from local working directory via rsync
- **Virtual environment management**: Automated setup with uv
- **Django support**: Migrations, static files, cache directories
- **Service management**: Systemd unit creation and lifecycle management
- **Monitoring**: Optional monitoring agent service
- **Traefik integration**: Automatic reverse proxy configuration

## Requirements

- Python 3.11+ on target host
- uv installed at `/usr/local/bin/uv`
- systemd-based Linux distribution

## Role Variables

See `defaults/main.yml` for all available variables. Key variables come from the service manifest:

```yaml
service:
  name: myapp
  strategy: rsync
  rsync:
    src: /local/path/to/app/
    dest: /opt/apps/myapp/src
    delete: true
    excludes: [".git/", "__pycache__/", "*.pyc"]
  app:
    user: app-myapp
    venv: /opt/apps/myapp/.venv
    install: "uv sync"
    cmd: "/opt/apps/myapp/.venv/bin/granian --workers 4 --host 0.0.0.0:8000 app:application"
    django:
      enabled: true
      settings_module: config.settings.production
      migrate: true
      collectstatic: true
  env:
    SECRET_KEY: "{{ vault_secret_key }}"
    DATABASE_URL: "sqlite:///{{ service_home }}/db.sqlite3"
```

## Example Playbook

```yaml
- hosts: webservers
  tasks:
    - name: Deploy Python application
      include_role:
        name: local.ops_library.python_app_systemd
      vars:
        service: "{{ manifest.service }}"
```

## Deployment Strategies

### Rsync (Working Tree)
Copies local working directory to target. Perfect for development and rapid iteration.

### Git (Coming Soon)
Clone from git repository with specific branch/tag.

### Artifact (Coming Soon)
Download pre-built artifacts from registry.

## Django Applications

When `service.app.django.enabled` is true:
- Runs migrations automatically
- Collects static files
- Creates cache directory
- Sets DJANGO_SETTINGS_MODULE environment variable

## Service Management

Creates systemd unit at `/etc/systemd/system/<service_name>.service` with:
- Automatic restart on failure
- Environment file support
- Proper user/group isolation
- Working directory configuration

## License

MIT