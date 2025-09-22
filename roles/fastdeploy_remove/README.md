# fastdeploy_remove Role

Cleanly removes an existing FastDeploy installation from a host.

## Features
- Stops and disables the FastDeploy systemd service.
- Drops FastDeploy PostgreSQL database and user (configurable).
- Removes application directories, virtual environments, and service files.
- Cleans up Traefik integration and sudoers entries created during deployment.
- Includes safety prompts/guards to avoid accidental removal in production.

## Variables
Key toggles are documented in `defaults/main.yml`, for example:
- `fastdeploy_remove_drop_database`: whether to drop the database.
- `fastdeploy_remove_preserve_services`: keep registered runner definitions.

## Example
```yaml
- hosts: macmini
  become: true
  roles:
    - role: local.ops_library.fastdeploy_remove
      vars:
        fastdeploy_remove_drop_database: false
```

## Notes
- Commonly invoked through `ops-control` via `just remove-fastdeploy`.
