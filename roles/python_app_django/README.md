# python_app_django Role

Legacy helper role for deploying generic Django applications using systemd.

## Features
- Creates application user, directories, and virtual environment.
- Syncs code via rsync or git depending on `service.strategy` inputs.
- Runs Django migrations and collects static files.
- Configures systemd service units and optional Traefik routes.

## Status
- Retained for compatibility with older manifest-driven workflows (`services.d/*`).
- New services are encouraged to use dedicated roles (e.g., `nyxmon_deploy`).

## Documentation
Refer to comments inside `tasks/main.yml` and related templates for available variables; the role expects the manifest-style `service.*` variable structure.
