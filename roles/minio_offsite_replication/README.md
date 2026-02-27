# minio_offsite_replication

Pull MinIO backup archives from a remote source host into offsite storage on the local host.

## Description

This role installs an rsync-over-SSH replication script and wires a systemd service + timer.
Each run:

1. Syncs archive files (`*.tar.gz`, `*.tar.zst` by default) from source -> destination.
2. Writes a status JSON file with latest archive metadata for monitoring/debugging.
3. Optionally fails when no archives are present (`minio_offsite_replication_require_archives`).

The role is intended for scenarios where MinIO runs on one host (e.g. `macmini`) and offsite
archive retention should live on another host (e.g. `fractal`).

Operational note:

- In environments that already run MinIO-to-MinIO bucket replication, this role is a
  secondary break-glass fallback for cold archive artifacts, not the primary protection path.

## Requirements

- Source host must expose backup archives via SSH.
- SSH key-based auth from destination host -> source host.
- `mail` command available when alerting is enabled.

## Role Variables

### Required

```yaml
minio_offsite_replication_source_host: "macmini.tailde2ec.ts.net"
minio_offsite_replication_source_path: "/mnt/cryptdata/backups/minio"
minio_offsite_replication_destination_path: "/tank/backups/minio"
```

### SSH

```yaml
minio_offsite_replication_ssh_key_manage: true
minio_offsite_replication_ssh_private_key: "{{ vault_replication_private_key }}"
minio_offsite_replication_ssh_key_path: "/root/.ssh/minio-offsite-replication-ed25519"
minio_offsite_replication_manage_known_hosts: true
minio_offsite_replication_ssh_known_hosts_path: "/root/.ssh/known_hosts"
```

### Schedule and behavior

```yaml
minio_offsite_replication_on_calendar: "05:00"
minio_offsite_replication_randomized_delay_sec: "15m"
minio_offsite_replication_archive_patterns:
  - "*.tar.gz"
  - "*.tar.zst"
minio_offsite_replication_rsync_delete: false
minio_offsite_replication_require_archives: false
minio_offsite_replication_destination_owner: "root"
minio_offsite_replication_destination_group: "root"
minio_offsite_replication_destination_mode: "0750"
minio_offsite_replication_status_group: "root"
minio_offsite_replication_status_mode: "0750"
minio_offsite_replication_latest_marker_file: "/var/lib/minio-offsite-replication/latest-archive.marker"
minio_offsite_replication_spindown_enabled: false
minio_offsite_replication_spindown_script_path: "/usr/local/bin/zfs-syncoid-spindown.sh"
```

With `minio_offsite_replication_rsync_delete: false` (default), the destination is append-only.

### Alerting

```yaml
minio_offsite_replication_alert_enabled: true
minio_offsite_replication_alert_email: "root"
minio_offsite_replication_alert_subject_prefix: "[minio-offsite]"
```

For the full list, see `defaults/main.yml`.

## Example Playbook

```yaml
- name: Configure MinIO offsite replication on fractal
  hosts: fractal
  become: true
  vars:
    minio_offsite_replication_ssh_private_key: "{{ vault_deploy_key }}"
  roles:
    - role: local.ops_library.minio_offsite_replication
      vars:
        minio_offsite_replication_source_host: "macmini.tailde2ec.ts.net"
        minio_offsite_replication_source_path: "/mnt/cryptdata/backups/minio"
        minio_offsite_replication_destination_path: "/tank/backups/minio"
        minio_offsite_replication_on_calendar: "05:00"
        minio_offsite_replication_alert_email: "root"
```

## Handlers

- `reload systemd` - reloads systemd daemon after unit changes
- `restart minio-offsite-replication-timer` - restarts timer after updates

## Tags

- `minio_offsite_replication`

## Testing

```bash
just test-role minio_offsite_replication
```

## License

MIT
