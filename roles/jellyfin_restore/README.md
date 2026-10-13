# Jellyfin Restore Role

Restores Jellyfin from an on-host backup archive (data, config, systemd unit, Traefik config, logs) and brings the service back online.

## Features
- Selects a specific archive or the latest available under `{{ jellyfin_restore_root }}`.
- Unpacks the payload, rsyncs data/config/logs back into place, and reloads systemd/Traefik when needed.
- Ensures Jellyfin directories and permissions are reset before restarting the service.

## Usage

```yaml
- hosts: media
  become: true
  roles:
    - role: local.ops_library.jellyfin_restore
      vars:
        jellyfin_restore_archive: "{{ archive | default('latest') }}"
```

## Key Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `jellyfin_restore_archive` | `latest` | Archive filename or `latest` to auto-select the newest. |
| `jellyfin_restore_root` | `/opt/backups/jellyfin` | Directory containing backup archives. |
| `jellyfin_restore_restart` | `true` | Restart (vs start) the service after restore. |
| `jellyfin_restore_cleanup` | `true` | Remove the staging directory after success. |
| `jellyfin_restore_staging_dir` | `/tmp/jellyfin-restore` | Temporary unpack location; override if restores exceed `/tmp` capacity. |

See `defaults/main.yml` and `roles/jellyfin_shared/defaults/main.yml` for the full variable reference.

## Retained pre-restore copies

Before replacing live data, the shared `restore_preserve_internal` tasks retain
a timestamped sibling. Ordinary directories are atomically renamed away; mount
points are copied with `cp -a` and verified by checksum and metadata before
emptying their contents. Insufficient space fails before live data changes.
Nested mounts and symlink targets are refused. Quiesce all writers and run only
one restore at a time; when service stopping is disabled, quiescing is the caller’s responsibility.

The final report prints the retained path and size in bytes. Restores **never
remove or prune these copies**, including on failure or a later restore. The
owner prunes old copies by hand after inspecting them. Exact path patterns:

- `{{ jellyfin_data_dir }}.pre-restore-*`
- `{{ jellyfin_config_dir }}.pre-restore-*`

Each `*` is a UTC timestamp plus a random suffix. Failed copy verification may
leave an incomplete sibling; inspect it manually. On failure, use the reported
copy to recover before starting services.
