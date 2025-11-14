# Homelab Backup Role

`homelab_backup` snapshots the SQLite database, media, static files, environment file, and supporting configs for the Homelab service. It follows the same `/opt/backups/<service>/<prefix>-<timestamp>` layout used by other ops-library roles so ops-control can reuse common playbooks and `just backup homelab`.

## Features

- Hot SQLite backups using `sqlite3 .backup` with automatic fallback to an offline snapshot
- Rsync-based copies of static/media/cache directories with optional `--delete`
- Captures `.env`, systemd unit, and Traefik config for auditing/restores
- Metadata (slug, timestamp, ops-library version, git commit if available) plus SHA256 manifest
- Optional tarball creation and fetch back to the control host

## Key Variables

```yaml
homelab_backup_prefix: manual                 # Prefix for backup directory/archive names
homelab_backup_root: /opt/backups/homelab     # Target directory on the remote host
homelab_backup_include_static: true
homelab_backup_include_media: true
homelab_backup_include_cache: false
homelab_backup_include_env: true
homelab_backup_include_systemd: true
homelab_backup_include_traefik: true
homelab_backup_force_stop: false              # Force offline snapshot instead of sqlite3 .backup
homelab_backup_sqlite_retries: 3              # Retries before falling back to offline snapshot
homelab_backup_create_archive: true
homelab_backup_archive_format: tar.gz
homelab_backup_fetch_local: true
homelab_backup_local_dir: "{{ lookup('env','HOME') }}/backups/homelab"
```

## Example Playbook

```yaml
- name: Backup Homelab
  hosts: macmini
  become: true
  roles:
    - role: local.ops_library.homelab_backup
      vars:
        homelab_backup_prefix: "manual"
        homelab_backup_fetch_local: true
```

## Notes

- The role requires `sqlite3` and `rsync` on the target host.
- Hot backups keep Homelab online, but if `.backup` fails after `homelab_backup_sqlite_retries`, the role briefly stops the service, copies the DB, and restarts it.
- Archives are named `<prefix>-<timestamp>.tar.gz` and stored under `homelab_backup_root`. When `homelab_backup_fetch_local` is true, the tarball is also fetched to `homelab_backup_local_dir` on the control node.
