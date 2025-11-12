# UniFi Backup Role

Creates a consistent on-host backup for the UniFi Network Application, combining a MongoDB dump, file snapshots, and metadata that document how to restore the archive.

## Features

- Validates the UniFi installation paths and required binaries (`mongodump`, `mongo`, `rsync`, `tar`).
- Performs a `mongodump` **before** the service stops to capture the embedded database safely.
- Stops `unifi.service`, rsyncs the data directory (including `.unf` autobackups) and optional logs, then restarts the service.
- Copies integration files (system.properties, keystore, environment file, systemd unit, Traefik config).
- Writes `metadata.yml` plus a `manifest.sha256` for integrity verification.
- Optionally compresses the snapshot into `tar.gz`/`tar.zst` and fetches it to the control node.

## Requirements

- Run with `become: true`.
- Target host must have UniFi installed under `/usr/lib/unifi` (override via defaults if custom).
- Packages listed in `unifi_backup_required_packages` must be available in the OS repositories (defaults to MongoDB tools, `rsync`, `tar`, `findutils`).

## Key Variables

See `defaults/main.yml` for the full list. Common overrides:

```yaml
unifi_backup_root: /opt/backups/unifi
unifi_backup_prefix: manual
unifi_backup_include_logs: false
unifi_backup_include_autobackups: true
unifi_backup_create_archive: true
unifi_backup_archive_format: tar.gz   # or tar.zst
unifi_backup_fetch_local: true
unifi_backup_local_dir: "{{ lookup('env','HOME') }}/backups/unifi"
unifi_backup_disk_check_enabled: true
unifi_backup_disk_overhead_ratio: 1.5
unifi_service_name: unifi.service
unifi_systemd_unit_path: /etc/systemd/system/unifi.service
unifi_traefik_config_path: /etc/traefik/dynamic/unifi.yml
unifi_mongodb_host: 127.0.0.1
unifi_mongodb_port: 27017
unifi_mongodb_username: unifi
unifi_mongodb_password: "{{ vault_unifi_mongodb_password }}"
unifi_mongodb_auth_db: admin
```

## Example

```yaml
- name: Take UniFi snapshot before upgrades
  hosts: unifi
  become: true
  roles:
    - role: local.ops_library.unifi_backup
      vars:
        unifi_backup_prefix: pre-upgrade
        unifi_backup_include_logs: true
        unifi_backup_archive_format: tar.zst
```

The run produces `/opt/backups/unifi/pre-upgrade-YYYYMMDDTHHMMSS/…` (plus `pre-upgrade-…tar.zst` if enabled) and copies the archive to `~/backups/unifi/` on the control node for off-host retention.
