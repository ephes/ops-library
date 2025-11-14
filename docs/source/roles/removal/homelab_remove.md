# Homelab Remove

Destroys a Homelab deployment safely and idempotently. The role enforces explicit confirmation and exposes granular flags to preserve selected data when needed.

## Highlights

- Requires `homelab_remove_confirm: true` before any destructive action.
- Stops/disables the systemd service, deletes the unit file, and removes the Traefik dynamic config (toggle via `homelab_remove_traefik_config`).
- Removes the `homelab` user, home directory, SQLite DB, and media tree when the corresponding `homelab_remove_*` flags remain `true`.
- Prints a removal plan and pauses when database/media deletion is requested, giving operators a chance to bail out and run a backup first.
- Idempotent: skips steps automatically if files/users already disappeared.

## Key Variables

- `homelab_remove_confirm` (**required**) – set to `true` to proceed.
- `homelab_remove_user` / `homelab_remove_home` – remove system account/home directory (default `true`).
- `homelab_remove_database`, `homelab_remove_media` – delete SQLite DB and media tree (default `true`).
- `homelab_remove_traefik_config` – remove `/etc/traefik/dynamic/homelab.yml`.
- `homelab_remove_auto_confirm` – set `true` to skip the interactive pause (useful for automation).

Usage example:

```yaml
- hosts: macmini
  become: true
  roles:
    - role: local.ops_library.homelab_remove
      vars:
        homelab_remove_confirm: true
        homelab_remove_database: false   # keep sqlite db
        homelab_remove_media: false      # keep uploaded files
```
