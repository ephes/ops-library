# zfs_syncoid_replication

Configure scheduled ZFS replication jobs using `syncoid`, with optional mail alerts and HDD spindown hooks.

## Description

This role installs `syncoid` (via the `sanoid` package), renders a systemd service + timer, and runs one or more
replication jobs in sequence. It can trigger a small alert script on failure and optionally run a post-backup
spindown script (e.g., `hdparm -y`) to quiet HDDs after the backup window.
If `readonly: true` is set on a job, the service passes `--recvoptions="o readonly=on"` so the target
datasets are created/updated as read-only without toggling properties between runs.

## Requirements

- ZFS pools/datasets already exist on the target host.
- `sanoid` snapshots are managed separately (this role **does not** configure snapshot policies).
- Outbound mail relay configured if alerting is enabled (e.g., via `mail_relay_client`).

## Role Variables

### Required

```yaml
zfs_syncoid_replication_jobs:
  - source: fast/general
    target: tank/replica/fast/general
    recursive: false
    readonly: true
    force_delete: false
    no_rollback: true
    prune_conflicting_snapshots: false
    prune_target_only_snapshots: false
    extra_args:
      - "--no-rollback"
```

`force_delete: true` adds `--force-delete` so syncoid can remove target-only snapshots that
would otherwise block incremental receives.
`no_rollback: false` removes `--no-rollback` from the default args for that job, allowing
syncoid to roll back the target to the most recent common snapshot.
`prune_conflicting_snapshots: true` runs a local preflight cleanup that destroys target
snapshots whose GUIDs do not match the source (or do not exist on the source).
`prune_target_only_snapshots: true` (only used with `prune_conflicting_snapshots`) also removes
snapshots that exist only on the target. Default is false for safety.

### Common

```yaml
zfs_syncoid_replication_on_calendar: "02:00"
zfs_syncoid_replication_randomized_delay_sec: "10m"
zfs_syncoid_replication_alert_email: "root"
zfs_syncoid_replication_spindown_devices:
  - /dev/disk/by-id/ata-EXAMPLE
zfs_syncoid_replication_spindown_pool: "tank"
zfs_syncoid_replication_spindown_retries: 10
zfs_syncoid_replication_spindown_sleep_sec: 60
```

### Advanced

```yaml
zfs_syncoid_replication_default_args:
  - "--no-rollback"
zfs_syncoid_replication_syncoid_path: "/usr/sbin/syncoid"
zfs_syncoid_replication_timeout_sec: "6h"
zfs_syncoid_replication_alert_subject_prefix: "[zfs-syncoid]"
```

For the full list, see `defaults/main.yml`.

## Dependencies

None.

## Example Playbook

```yaml
- name: Configure syncoid replication
  hosts: storage
  become: true
  roles:
    - role: local.ops_library.zfs_syncoid_replication
      vars:
        zfs_syncoid_replication_jobs:
          - source: fast/timemachine
            target: tank/replica/fast/timemachine
            readonly: true
            force_delete: false
            no_rollback: true
            prune_conflicting_snapshots: false
            prune_target_only_snapshots: false
            extra_args:
              - "--no-rollback"
        zfs_syncoid_replication_on_calendar: "02:00"
        zfs_syncoid_replication_alert_email: "root"
        zfs_syncoid_replication_spindown_devices:
          - /dev/disk/by-id/ata-WDC_WD120EFGX-EXAMPLE
        zfs_syncoid_replication_spindown_pool: "tank"
```

## Handlers

- `reload systemd` - reloads systemd daemon after unit changes
- `restart zfs-syncoid-replication-timer` - restarts the timer after updates

## Tags

- `zfs_syncoid_replication`

## Testing

```bash
just test-role zfs_syncoid_replication
```

## Changelog

- **1.0.0** (2026-01-18): Initial release

## License

MIT

## Author Information

Jochen Wersdoerfer
