# zfs_usb_replication

Configure a scheduled USB-attached ZFS replication workflow using `syncoid`, with optional mail alerts.

## Description

This role installs `syncoid` (via the `sanoid` package), writes a USB replication script, and wires a systemd
service + timer. The script checks for the configured USB device path, imports the ZFS pool when present,
loads the encryption key from a key file, runs the configured syncoid jobs, and exports the pool afterwards.
If the USB device is absent, the run logs a clean skip and exits successfully.
Every attempt is also recorded in `/var/lib/zfs-usb-replication/status.json`.
Missing-device skips update `last_attempt_*` while preserving
`last_present_attempt_*` and `last_success_at`, so monitoring can distinguish a
normal offsite rotation from an unresolved failure while a drive was attached.
Drive-present attempts also sample pool size, allocation, and free space before
export, so capacity alerting does not depend on a collector racing the temporary
pool import window.
When `readonly: true` is set on a job, the script passes `--recvoptions="o readonly=on"` so the target
datasets are created/updated as read-only without toggling properties between runs.
For `recursive: true` + `readonly: true` jobs, the script auto-sets `canmount=off` on existing target
parent datasets before `zfs mount -a` so read-only parents do not block child mountpoint creation.
Optional pre-sync retention policies prune old managed target-only snapshots
before replication. A policy refuses to prune without a common source/target
snapshot with the same name and ZFS GUID, and never removes snapshots that still
exist on the source.

The role also installs an attended, read-only snapshot-file attestation helper.
Given a closed request, it verifies that bounded files exist with exact byte
counts and SHA-256 digests in the newest source snapshot whose preserved ZFS
GUID also exists on a configured replica dataset. It does not run automatically
with replication.

## Requirements

- ZFS pool on the USB disk, with native encryption enabled.
- A key file stored on the host (managed by this role if `zfs_usb_replication_key_manage=true`).
- Outbound mail relay configured if alerting is enabled (e.g., via `mail_relay_client`).

## Role Variables

### Required

```yaml
zfs_usb_replication_device: /dev/disk/by-id/usb-EXAMPLE
zfs_usb_replication_pool: vault
zfs_usb_replication_key: "{{ vault_usb_key }}"
zfs_usb_replication_jobs:
  - source: tank/replica/fast
    target: vault/replica/fast
    recursive: true
    readonly: true
    force_delete: false
    no_rollback: true
    abort_partial_receive: false
```

`force_delete: true` adds `--force-delete` so syncoid can remove target-only snapshots that
would otherwise block incremental receives.
`no_rollback: false` removes `--no-rollback` from the default args for that job, allowing
syncoid to roll back the offsite target to the most recent common snapshot when the replica
has drifted since the last successful run.
`abort_partial_receive: true` aborts any leftover partial receive on the target dataset (and
descendants for recursive jobs) before running syncoid. Uses the shared abort script installed
by `zfs_syncoid_replication`. Default is `false`.

### Common

```yaml
zfs_usb_replication_on_calendar: "Sun 04:00"
zfs_usb_replication_alert_email: "root"
zfs_usb_replication_key_path: "/root/.zfs-key-vault"
zfs_usb_replication_identifier: "usb"
zfs_usb_replication_force_export: true
zfs_usb_replication_state_path: /var/lib/zfs-usb-replication/status.json
zfs_usb_replication_snapshot_retention:
  - source: tank/replica/fast/timemachine
    target: vault/replica/fast/timemachine
    keep_days: 60
    prefixes: [autosnap_, syncoid_primary_, syncoid_usb_]
```

Runtime mount safeguards:
- `zfs_usb_replication_exportfs_lock_dir` defaults to `/etc/exports.d` and is created before mounting.
- `zfs_usb_replication_set_canmount_off_for_readonly_recursive_targets` defaults to `true`.

Attestation installation:

- `zfs_usb_replication_attestation_helper_path` defaults to
  `/usr/local/sbin/zfs-snapshot-file-attestation` and is installed root-owned,
  mode `0750`.
- `zfs_usb_replication_attestation_dir` defaults to
  `/var/lib/zfs-usb-replication/attestations` and is root-owned, mode `0700`.

### Attended snapshot-file attestation

An external control playbook owns pool import/unlock/export and must place a
root-owned, mode-`0600` request directly in the private attestation directory.
The source dataset must already be mounted. The replica may remain unmounted:
the helper proves that its selected snapshot is the corresponding receive by
matching the ZFS snapshot GUID preserved by send/receive. A request is closed,
limited to 200 files and 1 MiB, and has this shape:

```json
{
  "schema_version": 1,
  "kind": "zfs_snapshot_file_replication_attestation_request",
  "request_id": "example-request-1",
  "created_at": "2026-01-01T12:00:00Z",
  "source_dataset": "sourcepool/example",
  "target_dataset": "targetpool/example",
  "files": [
    {
      "id": "example-file-1",
      "relative_path": "application/packages/example/manifest.json",
      "expected_bytes": 1234,
      "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    }
  ]
}
```

The external attended caller must pin and pass the absolute `zfs` and `zpool`
binary paths along with an exact dataset pair and a narrow allowed root:

```bash
sudo /usr/local/sbin/zfs-snapshot-file-attestation \
  --attestation-dir /var/lib/zfs-usb-replication/attestations \
  --request /var/lib/zfs-usb-replication/attestations/example.request.json \
  --response /var/lib/zfs-usb-replication/attestations/example.response.json \
  --expected-source sourcepool/example \
  --expected-target targetpool/example \
  --allowed-relative-root application/packages \
  --zfs-path /usr/sbin/zfs \
  --zpool-path /usr/sbin/zpool
```

The helper runs only fixed `zfs list/get` and `zpool get` argv under a minimal
locale-stable environment with time and output limits. It requires distinct
pool GUIDs, `readonly=on` and no receive resume token on the target, hashes each
single-link regular source-snapshot file through descriptor-relative traversal,
then re-queries both exact snapshot identities before atomically publishing a
mode-`0600` response. A blocked response contains a closed reason code and no
partial evidence.

The evidence means only that the selected source snapshot contains those exact
files and that a snapshot with the same preserved GUID was observed on another
pool. It does not prove retention, an independent failure domain, drive
detachment, transport, or physical offsite custody. Those remain separate
policy and human-attestation decisions.
When the requested file is a published package manifest, its exact containment
proves that this selected source snapshot contains that publication; a snapshot
timestamp alone would not.

### Spindown (optional)

```yaml
zfs_usb_replication_spindown_enabled: true
zfs_usb_replication_spindown_pool: "tank"  # pool to check for activity before parking HDDs
zfs_usb_replication_spindown_devices:
  - /dev/disk/by-id/ata-WDC_WD120EFGX-68CPHN0_WD-B00MJ7WD
  - /dev/disk/by-id/ata-WDC_WD120EFGX-68CPHN0_WD-B00MRZAD
```

Notes:
- `zfs_usb_replication_force_export: true` exports the USB pool after each run, even on failure.
- `zfs_usb_replication_state_path` stores durable host-local history for monitoring; do not place it on the removable pool.
- `zfs_usb_replication_snapshot_retention` runs before syncoid. Only snapshots
  older than `keep_days`, matching a configured prefix, and absent from the
  source are eligible. Manual/unmatched snapshots and all common anchors remain.
- `zfs_usb_replication_wait_for_async_destroy: true` waits for ZFS deferred frees
  to finish before starting the next receive.
- `zfs_usb_replication_spindown_pool` should be the HDD pool (the USB job reads from this pool).
- Spindown is invoked only after a successful replication run.

### Advanced

```yaml
zfs_usb_replication_default_args:
  - "--no-rollback"
zfs_usb_replication_syncoid_path: "/usr/sbin/syncoid"
zfs_usb_replication_timeout_sec: "8h"
zfs_usb_replication_alert_subject_prefix: "[zfs-usb]"
zfs_usb_replication_key_manage: true
zfs_usb_replication_exportfs_lock_dir: "/etc/exports.d"
zfs_usb_replication_set_canmount_off_for_readonly_recursive_targets: true
```

For the full list, see `defaults/main.yml`.

## Dependencies

- When `abort_partial_receive: true` is set on any job, the shared abort script from `zfs_syncoid_replication`
  must be installed on the host (at `zfs_usb_replication_abort_partial_receive_script_path`). If the script is
  absent, the job logs a warning and continues without aborting partial receives.

## Example Playbook

```yaml
- name: Configure USB replication
  hosts: storage
  become: true
  vars:
    zfs_usb_replication_key: "{{ vault_usb_key }}"
  roles:
    - role: local.ops_library.zfs_usb_replication
      vars:
        zfs_usb_replication_device: /dev/disk/by-id/usb-EXAMPLE
        zfs_usb_replication_pool: vault
        zfs_usb_replication_jobs:
          - source: tank/replica/fast
            target: vault/replica/fast
            recursive: true
            readonly: true
            no_rollback: false
            abort_partial_receive: true
        zfs_usb_replication_alert_email: root
```

## Handlers

- `reload systemd` - reloads systemd daemon after unit changes
- `restart zfs-usb-replication-timer` - restarts the timer after updates

## Tags

- `zfs_usb_replication`

## Testing

```bash
just test-role zfs_usb_replication
```

## Changelog

- **1.3.0** (2026-08-09): Added an attended, root-private, read-only snapshot-file replication attestation helper with bounded closed schemas and preserved-GUID verification.
- **1.2.0** (2026-03-18): Added per-job `no_rollback` and `force_delete` controls so offsite USB replicas can auto-heal target drift the same way the primary syncoid role can.
- **1.1.0** (2026-03-17): Added `abort_partial_receive` job option to self-heal stuck partial ZFS receives (uses shared script from `zfs_syncoid_replication`)
- **1.0.3** (2026-03-01): Hardened readonly recursive USB runs by auto-setting `canmount=off` on existing target parents and ensuring `/etc/exports.d` exists before `zfs mount -a`
- **1.0.2** (2026-01-30): Added force-export and spindown support for USB replication runs
- **1.0.1** (2026-01-29): Added `zfs_usb_replication_identifier` to avoid syncoid snapshot name collisions
- **1.0.0** (2026-01-18): Initial release

## License

MIT

## Author Information

Jochen Wersdoerfer
