# UniFi Restore Role

Restores a UniFi Network Application from a snapshot created by `unifi_backup`. The role supports two workflows:

1. **Automated** (default): drops/restores the MongoDB database, rsyncs the data directory, reapplies systemd/Traefik files, and verifies service health.
2. **Manual .unf prep**: extracts the most recent `.unf` file to `/tmp/unifi-restore.unf` so an administrator can import it via the UniFi web UI. Cleanup removes the file automatically once the run finishes.

## Features

- Validates archive availability (`latest` selection supported) and required tooling.
- Optionally creates a pre-restore safety backup (via `unifi_backup`) and can roll back automatically if verification fails.
- Extracts the archive into a staging directory, validates `manifest.sha256`, and checks UniFi major version compatibility.
- Provides MongoDB restore + rsync of the UniFi data directory or prepares a `.unf` for manual import.
- Copies system integration files (systemd unit, Traefik config) and reloads `systemd`.
- Waits for `unifi.service`, `mongo`, and (optionally) the HTTPS interface to come back online.

## Requirements

- Run with `become: true`.
- Backups must have been produced by the companion `unifi_backup` role (directory layout is assumed).
- `mongorestore`, `mongo`, `rsync`, `tar`, and `sha256sum` must be available (installed automatically via `unifi_restore_required_packages`).

## Key Variables

See `defaults/main.yml` for the full list. Common overrides:

```yaml
unifi_restore_archive: latest                        # or specific filename
unifi_restore_archive_search_root: /opt/backups/unifi
unifi_restore_create_safety_backup: true
unifi_restore_method: automated                      # or manual-unf-prep
unifi_restore_validate_checksums: true
unifi_restore_check_version_compatibility: true
unifi_restore_health_url: https://controller.example.com/
unifi_restore_staging_dir: /tmp/unifi-restore
unifi_restore_service_stop_pause: 10
unifi_restore_service_start_timeout: 120
unifi_restore_mongodb_host: 127.0.0.1
unifi_restore_mongodb_port: 27017
unifi_restore_mongodb_database: unifi
unifi_restore_mongodb_username: unifi
unifi_restore_mongodb_password: "{{ vault_unifi_mongodb_password }}"
unifi_restore_mongodb_auth_db: admin
```

## Example

```yaml
- name: Restore UniFi from latest backup
  hosts: unifi
  become: true
  roles:
    - role: local.ops_library.unifi_restore
      vars:
        unifi_restore_archive_search_root: /opt/backups/unifi
        unifi_restore_health_url: https://unifi.example.net/
```

To prepare a manual `.unf` import instead:

```yaml
- role: local.ops_library.unifi_restore
  vars:
    unifi_restore_method: manual-unf-prep
    unifi_restore_create_safety_backup: false
```

The play reports where `/tmp/unifi-restore.unf` was placed so you can upload it via the UniFi UI before cleanup removes the file.
