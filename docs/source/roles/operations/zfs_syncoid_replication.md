# ZFS Syncoid Replication

Schedules local ZFS replication jobs using syncoid, with optional mail alerts and a post-backup spindown hook.

## Highlights

- Runs one or more syncoid jobs sequentially from a systemd timer.
- Supports recursive replication per job and an optional readonly toggle for targets.
- Optional alert script triggers via `OnFailure` and includes recent journal output.
- Optional spindown script can park HDDs after a successful replication window.

## Key Variables

- `zfs_syncoid_replication_jobs` - list of replication jobs (source -> target).
- `zfs_syncoid_replication_on_calendar` - systemd schedule for replication.
- `zfs_syncoid_replication_alert_email` - alert recipient.
- `zfs_syncoid_replication_spindown_devices` - devices to spin down after success.
- `readonly: true` in a job uses `--recvoptions="o readonly=on"` so target datasets stay read-only
  without property toggling between runs.

Example usage:

```yaml
- hosts: fractal
  become: true
  roles:
    - role: local.ops_library.zfs_syncoid_replication
      vars:
        zfs_syncoid_replication_jobs:
          - source: fast/general
            target: tank/replica/fast/general
            readonly: true
```
