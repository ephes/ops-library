# MeTube Restore Role

Restores MeTube from archives produced by `metube_backup`, reapplying state/config/systemd/Traefik files.

- Selects a specific archive or `latest` under `{{ metube_restore_root }}`.
- Restores `{{ metube_state_dir }}` into a fresh directory (the old one is kept aside), env file to `{{ metube_env_file }}`, systemd unit, and Traefik config.
- Stops the service during restore and restarts afterwards (toggles via `metube_restore_stop_service`/`metube_restore_restart`).
- `metube_restore_safety_root` (default `/var/backups/metube-pre-restore`) holds the config file copies.

### Safety copies and rollback

- The archive is unpacked into staging and checked (the state directory must be there) **before** MeTube
  is stopped.
- The stop must succeed and MeTube must be confirmed `inactive`/`failed`, otherwise the run aborts with the live state untouched (also with `metube_restore_stop_service: false`, where MeTube must already be stopped).
- The config files the restore replaces (env file, systemd unit, Traefik file) are copied to
  `metube_restore_safety_root/<UTC timestamp>/files/` (default `/var/backups/metube-pre-restore`).
- The live state directory is renamed to `<dir>.pre-restore-<UTC timestamp>` next to itself, and the
  archive is restored into a fresh, empty directory. There is no `rsync --delete` over live
  data any more. The rename is free on the same filesystem; a directory that is a mount point is
  refused before anything moves. A symlinked directory is resolved and its target is moved.
  The restored copy needs as much free space as the archive's state directory.
- If any step from the move to the final start fails, the role stops MeTube, moves the old
  directory and config files back, starts MeTube again on the old data (only after a
  successful rollback) and fails with the outcome and the safety paths.
- A successful run deletes older `<dir>.pre-restore-*` copies and older safety directories and
  keeps only its own, so one generation stays on disk until the next restore. An old copy that is or contains a mount point is never deleted; the run logs it and keeps it. Delete it once the
  restored instance is verified.
- The staging directory is removed in an `always` section, also after a failure.

Example:

```yaml
- hosts: macmini
  become: true
  roles:
    - role: local.ops_library.metube_restore
      vars:
        metube_restore_archive: "{{ archive | default('latest') }}"
```
