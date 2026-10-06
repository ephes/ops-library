# Navidrome Restore Role

Restores Navidrome from archives produced by `navidrome_backup`, reconstituting data/config/systemd/Traefik wiring and optionally forcing a full rescan.

## Features
- Selects an explicit archive or the most recent `*.tar.gz` under `{{ navidrome_restore_root }}`.
- Extracts into a staging area, restores data into a fresh directory (the old one is kept aside), restores config, Traefik + systemd units, merges logs, and restarts the service.
- Optional full rescan after restore to refresh the music index.

## Safety copies and rollback

- The archive is unpacked into staging and checked (the data directory must be there) **before** Navidrome
  is stopped.
- The stop must succeed and Navidrome must be confirmed `inactive`/`failed`, otherwise the run aborts with the live data untouched.
- The config files the restore replaces (`navidrome.toml`, systemd unit, Traefik file) are copied to
  `navidrome_restore_safety_root/<UTC timestamp>/files/` (default `/var/backups/navidrome-pre-restore`).
- The live data directory (with the cache inside it) is renamed to `<dir>.pre-restore-<UTC timestamp>` next to itself, and the
  archive is restored into a fresh, empty directory. There is no `rsync --delete` over live
  data any more. The rename is free on the same filesystem; a directory that is a mount point is
  refused before anything moves. A symlinked directory is resolved and its target is moved.
  The restored copy needs as much free space as the archive's data directory.
- If any step from the move to the final start fails, the role stops Navidrome, moves the old
  directory and config files back, starts Navidrome again on the old data (only after a
  successful rollback) and fails with the outcome and the safety paths.
- A successful run deletes older `<dir>.pre-restore-*` copies and older safety directories and
  keeps only its own, so one generation stays on disk until the next restore. An old copy that is or contains a mount point is never deleted; the run logs it and keeps it. Delete it once the
  restored instance is verified.
- The staging directory is removed in an `always` section, also after a failure.

Logs are merged into the log directory as before and are not rolled back. The optional full
rescan runs after a successful restore and does not trigger the rollback.

## Usage

```yaml
- hosts: media
  become: true
  roles:
    - role: local.ops_library.navidrome_restore
      vars:
        navidrome_restore_root: /opt/backups/navidrome
        navidrome_restore_archive: "{{ archive | default('latest') }}"
        navidrome_restore_force_full_rescan: true
```

## Key Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `navidrome_restore_root` | `/opt/backups/navidrome` | Location of backup archives. |
| `navidrome_restore_archive` | `latest` | Archive filename or `latest` to pick the newest. |
| `navidrome_restore_cleanup` | `true` | Remove the staging directory (also after a failure). |
| `navidrome_restore_safety_root` | `/var/backups/navidrome-pre-restore` | Parent of the timestamped config file copies. |
| `navidrome_restore_restart` | `true` | Restart service after restore. |
| `navidrome_restore_force_full_rescan` | `false` | Run `navidrome scan --full` after restore. |
