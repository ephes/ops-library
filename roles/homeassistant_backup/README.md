# Home Assistant Backup Role

Ansible role that creates an on-host backup of a Home Assistant Core deployment.

## Features

- Validates key paths (config, data, logs, systemd unit, Traefik dynamic file).
- Creates a timestamped directory under `/opt/backups/homeassistant` (configurable).
- Copies configuration, data, and optionally logs via `rsync`.
- Optionally snapshots Thread (OTBR) and Matter Server state directories.
- Captures the active systemd unit and Traefik router definition.
- Writes `metadata.yml` and a `manifest.sha256` file for integrity verification.
- Optionally compresses the snapshot into `tar.gz` alongside the directory.
- Copies the compressed archive back to the control machine for off-host storage.

By default the role also captures `/var/lib/thread` and any Matter Server
storage or chip factory directories that live outside the main data path.
Override `homeassistant_backup_extra_dirs` if you need a different set.

## Requirements

- The target host must have `rsync`, `find`, `sha256sum`, and `xargs`.
- Run with privilege escalation (`become: true`) so the role can read system files and write under `/opt`.

## Variables

Key settings (see `defaults/main.yml` for the full list):

```yaml
homeassistant_backup_root: /opt/backups/homeassistant
homeassistant_backup_prefix: manual
homeassistant_config_path: /home/homeassistant/site/config
homeassistant_data_path: /home/homeassistant/site/data
homeassistant_logs_path: /home/homeassistant/site/logs
homeassistant_backup_include_logs: true
homeassistant_backup_use_delete: true
homeassistant_backup_generate_checksums: true
homeassistant_backup_create_archive: true
homeassistant_backup_archive_format: tar.gz
homeassistant_backup_fetch_local: true
homeassistant_backup_local_dir: "{{ lookup('env','HOME') }}/backups/homeassistant"
homeassistant_service_unit_path: /etc/systemd/system/homeassistant.service
homeassistant_traefik_config_path: /etc/traefik/dynamic/homeassistant.yml
homeassistant_backup_otbr_state_path: /var/lib/thread
homeassistant_matter_server_storage_path: "{{ homeassistant_data_path }}/matter-server"
homeassistant_matter_server_chip_factory_dir: /data
```

Set `homeassistant_backup_prefix` (e.g. `pre-deploy`, `auto`) to organise snapshots.

## Example

```yaml
- name: Snapshot Home Assistant before changes
  hosts: homelab
  become: true
  roles:
    - role: local.ops_library.homeassistant_backup
      vars:
        homeassistant_backup_prefix: pre-deploy
```

This produces a directory on the target host such as `/opt/backups/homeassistant/pre-deploy-20250115T213000/config/…`
and a compressed archive `pre-deploy-20250115T213000.tar.gz` in the same backup root, which is also fetched to
`~/backups/homeassistant/` (customisable via `homeassistant_backup_local_dir`) on the control machine.
