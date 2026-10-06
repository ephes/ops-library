# Vaultwarden Restore Role

Restore Vaultwarden password manager from a backup archive.

## Disposition

`vaultwarden_restore` is `deprecated`. Echoport is the preferred operator path
for routine Vaultwarden restores. This role is retained for compatibility with
existing playbooks and legacy/manual workflows. ops-control gates its
`just restore vaultwarden` playbook behind an explicit confirmation.

## Quick Start

```yaml
# Restore from latest backup
- hosts: server
  roles:
    - role: local.ops_library.vaultwarden_restore
      vars:
        vaultwarden_restore_archive: latest

# Restore from specific backup
- hosts: server
  roles:
    - role: local.ops_library.vaultwarden_restore
      vars:
        vaultwarden_restore_archive: manual-20241207T120000.tar.gz
```

## Role Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `vaultwarden_restore_archive` | `latest` | Archive filename or "latest" (newest by controller mtime) |
| `vaultwarden_restore_local_dir` | — | Controller directory holding the archives |
| `vaultwarden_restore_age_identity` | — | age identity for `*.tar.gz.age` archives |
| `vaultwarden_restore_root` | `/opt/backups/vaultwarden` | Backup directory |
| `vaultwarden_restore_restart` | `true` | Restart service after restore |
| `vaultwarden_restore_cleanup` | `true` | Remove the remote staging directory (also after a failure) |
| `vaultwarden_restore_safety_root` | `/var/backups/vaultwarden-pre-restore` | Remote parent of the timestamped pre-restore safety copies |

## Safety

The role refuses or rolls back instead of leaving a half-restored vault:

1. The staged `db.sqlite3` must exist and pass `PRAGMA integrity_check`
   before the service is touched.
2. If `attachments`, `sends`, `db.sqlite3` or a key file under the data
   directory is a symlink, the role refuses before stopping anything: the
   safety copy would only keep the link, not the files behind it.
3. The service stop must succeed and `systemctl is-active` must report it
   down. Otherwise the run fails with the live data untouched. A host without
   the unit installed (fresh rebuild) skips the stop.
4. After the stop, the role copies the whole data directory (DB with its
   `-wal`/`-shm`, keys, attachments, sends) and the config, systemd override
   and Traefik file to `<vaultwarden_restore_safety_root>/<UTC timestamp>/`
   (`root`, `0700`) and prints the path. If the copy fails, nothing is
   overwritten.
5. `db.sqlite3-wal`, `-shm` and `-journal` are removed before the database is
   copied, so SQLite cannot replay an old WAL over the restored file.
6. rsync, key and config copy failures are fatal. Keys missing from the
   archive are skipped, as in the Echoport runner.
7. Any failure while overwriting (including the final start) puts the safety
   copy back (`rsync -a --delete --checksum` for the data directory) and fails with
   Vaultwarden **left stopped**. Check the data and start it by hand.
8. The decrypted archive on the controller and the remote staging directory
   are removed in an `always` section, so a failed run leaves no plaintext
   copy behind (unless `vaultwarden_restore_cleanup: false`).

Disk space: each run needs room for one copy of the data directory under
`vaultwarden_restore_safety_root`. Nothing prunes these copies. Delete one
once the restored vault is verified.

## What Gets Restored

- SQLite database (`db.sqlite3`)
- Attachments directory
- Sends directory
- RSA key files
- Configuration file (`/etc/vaultwarden.env`)
- Systemd override configuration
- Traefik dynamic configuration

## Dependencies

This role depends on `vaultwarden_shared` for common variable definitions.
