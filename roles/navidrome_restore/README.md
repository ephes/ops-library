# Navidrome Restore Role

Restores Navidrome from archives produced by `navidrome_backup`, reconstituting data/config/systemd/Traefik wiring and optionally forcing a full rescan.

## Features
- Selects an explicit archive or the most recent `*.tar.gz` under `{{ navidrome_restore_root }}`.
- Extracts into a staging area, rsyncs data/config/logs, restores Traefik + systemd units, and restarts the service.
- Optional full rescan after restore to refresh the music index.

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
| `navidrome_restore_cleanup` | `true` | Remove staging directory after restore. |
| `navidrome_restore_restart` | `true` | Restart service after restore. |
| `navidrome_restore_force_full_rescan` | `false` | Run `navidrome scan --full` after restore. |

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

- `{{ navidrome_data_dir }}.pre-restore-*`

Each `*` is a UTC timestamp plus a random suffix. Failed copy verification may
leave an incomplete sibling; inspect it manually. On failure, use the reported
copy to recover before starting services.
