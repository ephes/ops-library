# host_storage_migrate

Install an attended migration tool for existing local backup and Docker storage
to an already mounted external filesystem. The role itself only installs the
tool and its private configuration; it never stops services or migrates data.

## Requirements and variables

Linux with systemd, Python 3.11+, rsync, Docker Engine with its default buildx
builder, and an existing external mount. Run as root in a quiet maintenance
window. This is a bounded operator tool, not a general filesystem migrator.

| Variable | Default | Purpose |
| --- | --- | --- |
| `host_storage_migrate_mount` | empty | Required external mountpoint |
| `host_storage_migrate_uuid` | empty | Required exact external filesystem UUID |
| `host_storage_migrate_root` | empty | New private directory below that mount |
| `host_storage_migrate_cache_bytes` | `10000000000` | Native Docker GC target, positive integer bytes |
| `host_storage_migrate_health_timeout` | `300` | Seconds to wait for the prior container health state, at most 3600 |
| `host_storage_migrate_busy_sqlite` | empty list | Optional `{path, query}` read-only SQLite count queries; nonzero refuses cutover |
| `host_storage_migrate_sources` | `/opt/backups`, `/var/lib/docker`, `/var/lib/containerd` | Bounded supported source directories |

The optional additional supported backup source is
`/var/backups/security-trust-remediation`. Its content is relocated intact;
this tool does not decide its retention deadline or restore old trust bundles.

```yaml
- hosts: container_host
  roles:
    - role: local.ops_library.host_storage_migrate
      host_storage_migrate_mount: /mnt/data
      host_storage_migrate_uuid: CHANGEME-filesystem-uuid
      host_storage_migrate_root: /mnt/data/host-storage
```

Run `/usr/local/sbin/host-storage-migrate prepare` to check the mount, record
source identities and warm-copy files without stopping services. Then run
`cutover` in tmux. It records active Docker-dependent services (including
transitive Requires/BindsTo/PartOf/Wants/After consumers), stops consumers first, then Docker/socket, then containerd, and copies
and checksum-verifies data offline, mounts external trees at their original
paths and restores the previously active services. Cross-tree hardlinks, ACLs,
xattrs and ownership are preserved by one rsync invocation. Existing Docker
daemon configuration is merged with the native cache size policy, validated
before stopping services and backed up privately. No container image is pruned.
Unit preflight also runs online, before stopping anything, with the complete
host unit search path so dependencies generated from fstab are included.
Failed commands keep their detailed diagnostics in private files under
`/var/lib/host-storage-migrate`; shared logs only report the failed command.

The external UUID and exact bind identities are checked, and Docker/containerd
require the bind mounts. Missing storage must prevent engine startup. Original
source paths become mode-000 mountpoints; this is additional protection for
unprivileged callers, not a substitute for root-run backup jobs checking the
mount before writing. Retain those guards in the owning backup workflow.
The backup path additionally uses a persistent automount, so access triggers
the external bind mount and fails if that storage is unavailable. Docker's
mount dependencies protect engine startup. Coordinate a quiet window: SQLite
guards are admission checks and cannot lock out another operator's deployment.

`verify` checks mount identities, previously active services, and the original
running containers' names, image IDs and health (container IDs may change when
Compose units recreate them). It does not prove application HTTP health: verify
that separately before finalizing. Before external access, `cutover` failures
attempt a best-effort restoration of original files, daemon configuration and
service activity, reporting each failure. Once external mounts have been
exposed, new writes may exist there: failures retain external storage and set
`needs_attention`; they never automatically activate stale copies. `recover`
retries pre-exposure recovery or completes external activation as appropriate.
Private state remains under `/var/lib/host-storage-migrate`. Never blindly retry
a partial cutover. The tool refuses ambiguous state. After a verified pre-exposure rollback,
`prepare` can refresh the retained external warm copy and save the prior
receipt before a new cutover. Starting uses the reverse engine/consumer order.

After independent application/backup checks, `finalize` removes only the recorded
old source directories. It rechecks their identities and rejects nested mounts
before deletion. The external copies are retained. This is relocation, not
backup expiry. A reboot is a separate attended verification operation; do not
unplug the production disk to test failure behavior.
