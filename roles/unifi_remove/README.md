# UniFi Remove Role

Destructively removes the UniFi Network Application plus the supporting MongoDB/Java packages from the macmini host. The role mirrors the operational flow of the legacy teardown script but adds confirmation gates, optional backups, and granular `preserve_*` toggles so day‑2 cleanup stays deterministic.

## Features

- Optional pre-removal `local.ops_library.unifi_backup` execution to capture the last known-good snapshot.
- Graceful stop/disable of UniFi + MongoDB services, systemd unit removal, and Traefik/ufw cleanup.
- Package purge blocks for UniFi, MongoDB, and OpenJDK (toggle via `unifi_remove_packages`).
- Fine-grained directory cleanup flags (cache, logs, data, home) and optional MongoDB database/user drop commands.
- Human-readable summary at the end so you know exactly which destructive toggles fired.

## Key Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `unifi_remove_confirm` | `false` | Hard guard. Set to `true` (or use the Just target) before running. |
| `unifi_remove_trigger_backup` | `false` | When true, runs `local.ops_library.unifi_backup` first (configure that role via regular vars). |
| `unifi_remove_packages` | `true` | Purges UniFi, MongoDB, and Java packages. |
| `unifi_remove_delete_data` | `false` | Delete `/usr/lib/unifi` + `data`. Flip to `true` only after backups. |
| `unifi_remove_delete_home` | `false` | Remove the `unifi` home directory. |
| `unifi_remove_manage_firewall` | `true` | Delete ufw rules matching the standard UniFi ports. |
| `unifi_remove_drop_mongodb_database` | `false` | Drop the `unifi` MongoDB database (requires `unifi_mongodb_password`). |

Refer to `defaults/main.yml` for additional knobs (service list, directories, Mongo credentials, Traefik paths).

## Example Usage

```yaml
- hosts: macmini
  become: true
  roles:
    - role: local.ops_library.unifi_remove
      vars:
        unifi_remove_confirm: true
        unifi_remove_trigger_backup: true
        unifi_backup_root: "/srv/backups/unifi"
        unifi_backup_create_archive: true
        unifi_remove_delete_data: true
        unifi_remove_delete_home: true
        unifi_remove_drop_mongodb_database: true
        unifi_mongodb_password: "{{ sops_unifi_mongodb_password }}"
```

## Notes

- Dropping the MongoDB database/user requires valid credentials; the tasks stay skipped (and safe) until `unifi_mongodb_password` is set.
- Keep `unifi_remove_delete_data`/`home` set to `false` for dry-runs—once flipped the directories are removed permanently.
- If `ufw` is not installed the firewall cleanup step is quietly skipped.
