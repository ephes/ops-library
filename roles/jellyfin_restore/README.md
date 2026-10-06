# Jellyfin Restore Role

Restores Jellyfin from an on-host backup archive (data, config, systemd unit, Traefik config, logs) and brings the service back online.

## Features
- Selects a specific archive or the latest available under `{{ jellyfin_restore_root }}`.
- Unpacks the payload, restores data/config into fresh directories (the old ones are kept aside), merges logs, and reloads systemd/Traefik when needed.
- Ensures Jellyfin directories and permissions are reset before restarting the service.

## Safety copies and rollback

- The archive is unpacked into staging and checked (the data directory must be there) **before** Jellyfin
  is stopped.
- The stop must succeed and Jellyfin must be confirmed `inactive`/`failed`, otherwise the run aborts with the live data untouched (also with `jellyfin_restore_stop_service: false`, where Jellyfin must already be stopped).
- The config files the restore replaces (systemd unit, Traefik file) are copied to
  `jellyfin_restore_safety_root/<UTC timestamp>/files/` (default `/var/backups/jellyfin-pre-restore`).
- The live data directory (and the config directory, when the archive has one) is renamed to `<dir>.pre-restore-<UTC timestamp>` next to itself, and the
  archive is restored into a fresh, empty directory. There is no `rsync --delete` over live
  data any more. The rename is free on the same filesystem; a directory that is a mount point is
  refused before anything moves. A symlinked directory is resolved and its target is moved. A config directory inside the data directory (or the reverse)
  is refused, as is a safety root inside either.
  The restored copy needs as much free space as the archive's data directory.
- If any step from the move to the final start fails, the role stops Jellyfin, moves the old
  directories and config files back, starts Jellyfin again on the old data (only after a
  successful rollback) and fails with the outcome and the safety paths.
- A successful run deletes older `<dir>.pre-restore-*` copies and older safety directories and
  keeps only its own, so one generation stays on disk until the next restore. An old copy that is or contains a mount point is never deleted; the run logs it and keeps it. Delete it once the
  restored instance is verified.
- The staging directory is removed in an `always` section, also after a failure.

Logs are merged into the log directory as before and are not rolled back.

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
| `jellyfin_restore_cleanup` | `true` | Remove the staging directory (also after a failure). |
| `jellyfin_restore_stop_service` | `true` | Stop Jellyfin; with `false` it must already be stopped. |
| `jellyfin_restore_safety_root` | `/var/backups/jellyfin-pre-restore` | Parent of the timestamped config file copies. |
| `jellyfin_restore_staging_dir` | `/tmp/jellyfin-restore` | Temporary unpack location; override if restores exceed `/tmp` capacity. |

See `defaults/main.yml` and `roles/jellyfin_shared/defaults/main.yml` for the full variable reference.
