# Nyxmon Remove Role

Removes the Nyxmon monitoring service from a host.

## Features
- Stops and disables Nyxmon-related systemd services (app and monitor).
- Removes application directories, virtual environment, and cached assets.
- Optionally preserves the SQLite database for later reuse.
- Cleans up Traefik configuration and Telegram secrets stored on disk.

## Variables
See `defaults/main.yml` for options:
- `nyxmon_remove_preserve_database`: keep `db.sqlite3` when set to `true`.
- `nyxmon_remove_clean_traefik`: control whether Traefik routes are removed.

## Example
```yaml
- hosts: homelab
  become: true
  roles:
    - role: local.ops_library.nyxmon_remove
      vars:
        nyxmon_remove_preserve_database: true
```

## Notes
- Exposed in `ops-control` via `just remove-nyxmon`.
