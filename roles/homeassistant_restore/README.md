# Home Assistant Restore Role

Role that restores a Home Assistant Core deployment from backups produced by `homeassistant_backup`.

## Features

- Resolves backup archives by explicit path or automatically selects the latest archive on the target host.
- Optionally uploads an archive from the control machine cache when it is missing on the host.
- Extracts the archive into a timestamped staging directory and validates `metadata.yml` plus `manifest.sha256`.
- Creates a safety snapshot of the current site directory before applying changes for easy rollback.
- Stops Home Assistant, syncs configuration/data/logs via `rsync --delete`, and optionally restores systemd/Traefik files.
- Restarts the service, performs optional HTTP health checks, and triggers rollback automatically if verification fails.
- Cleans up staging and (optionally) the safety snapshot after a successful restore.

## Requirements

- Root privileges on the target host (the role copies files under `/home` and `/etc`).
- `rsync`, `tar`, `sha256sum`, and `python3` available on the managed node.
- Backups created with the companion `homeassistant_backup` role.

## Variables

Important settings (see `defaults/main.yml` for the full list):

```yaml
homeassistant_restore_archive: latest                   # or manual-20251108T123000.tar.gz
homeassistant_restore_archive_search_root: /opt/backups/homeassistant
homeassistant_restore_local_cache: "{{ lookup('env','HOME') }}/backups/homeassistant"
homeassistant_restore_validate_checksums: true
homeassistant_restore_dry_run: false
homeassistant_restore_system_files: false
homeassistant_restore_create_safety_backup: true
homeassistant_restore_cleanup_safety_backup: true
homeassistant_restore_verify_http: true
homeassistant_restore_health_url: http://localhost:10020
homeassistant_restore_dirs:
  - { name: config, dest: /home/homeassistant/site/config, optional: false }
  - { name: data,   dest: /home/homeassistant/site/data,   optional: false }
  - { name: logs,   dest: /home/homeassistant/site/logs,   optional: true }
```

## Example

```yaml
- name: Restore Home Assistant from the most recent backup
  hosts: homelab
  become: true
  roles:
    - role: local.ops_library.homeassistant_restore
      vars:
        homeassistant_restore_archive: latest
        homeassistant_restore_system_files: true
```

Run in dry-run/validation mode to verify integrity without touching the live installation:

```bash
ansible-playbook -i inventories/prod/hosts.yml playbooks/homeassistant/restore.yml \
  -e restore_archive=manual-20251108T123000.tar.gz -e dry_run=true
```
