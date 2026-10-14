# MeTube Restore Role

Restores MeTube from archives produced by `metube_backup`, reapplying state/config/systemd/Traefik files.

- Selects a specific archive or `latest` under `{{ metube_restore_root }}`.
- Restores `{{ metube_state_dir }}` via rsync, env file to `{{ metube_env_file }}`, systemd unit, and Traefik config.
- Stops the service during restore and restarts afterwards (toggles via `metube_restore_stop_service`/`metube_restore_restart`).

Example:

```yaml
- hosts: macmini
  become: true
  roles:
    - role: local.ops_library.metube_restore
      vars:
        metube_restore_archive: "{{ archive | default('latest') }}"
```

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

- `{{ metube_state_dir }}.pre-restore-*`

Each `*` is a UTC timestamp plus a random suffix. Failed copy verification may
leave an incomplete sibling; inspect it manually. On failure, use the reported
copy to recover before starting services.
