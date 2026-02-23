# OpenClaw Remove Role

Safely removes the OpenClaw deployment from a host with explicit confirmation and opt-in destructive flags.

## Quick Start

```yaml
- hosts: macmini
  become: true
  roles:
    - role: local.ops_library.openclaw_remove
      vars:
        openclaw_remove_confirm: true
        openclaw_remove_data: false
        openclaw_remove_image: false
        openclaw_remove_user: false
```

## Role Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `openclaw_remove_confirm` | `false` | Must be `true` to proceed. |
| `openclaw_remove_data` | `false` | Remove persistent data at `{{ openclaw_data_dir }}`. |
| `openclaw_remove_image` | `false` | Remove Docker image ids for repository `openclaw`. |
| `openclaw_remove_user` | `false` | Remove `openclaw` user and group. |
| `openclaw_remove_traefik_config` | `true` | Remove Traefik dynamic config. |
| `openclaw_remove_site_dir` | `true` | Remove `{{ openclaw_site_dir }}`. |
| `openclaw_remove_build_dir` | `true` | Remove `{{ openclaw_build_dir }}`. |
| `openclaw_remove_log_dir` | `true` | Remove `{{ openclaw_log_dir }}`. |

## Behavior

- Stops/disables the `openclaw` systemd service and removes its unit file.
- Removes the Docker compose stack (best effort) and known OpenClaw containers.
- Optionally removes OpenClaw Docker images.
- Removes compose/site/build/log artifacts and logrotate config.
- Optionally removes Traefik config, persistent data, and service user/group.

## Safety Notes

- Data deletion is opt-in (`openclaw_remove_data: true`).
- Image and user removal are also opt-in.
- Re-running the role is safe: already-removed artifacts do not cause hard failures.
- In production (`ops-control`), `openclaw_data_dir` is explicitly set to `/mnt/cryptdata/openclaw/data`.
- OpenClaw backup/restore is an Echoport lifecycle exception: do not expect `openclaw_backup`/`openclaw_restore` roles, and use `ops-control/docs/OPENCLAW_RUNBOOK.md` for restore-drill/operator commands.
