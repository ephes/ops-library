# daybook_operations_api_backup

Create a private operations database/replay-configuration archive.

The deploy role and its dedicated database must already exist. The play runs privileged for service control; database/archive commands run as the service account.
The service-owned lifecycle tool uses pg_dump with credentials in the child
environment, not argv. A unique mode-0600 tar contains the custom-format database,
server keyring/environment, profile configuration and a SHA-256 manifest.
Temporary files remain within a mode-0700 directory owned by the service account. Do not run deployment/key
rotation concurrently. No local source ledger or audio is included.

Example:

```yaml
- role: local.ops_library.daybook_operations_api_backup
```

The output reports the archive path only. Copy archives to protected backup
storage and monitor free space; automatic archive pruning is not enabled. Server
admission bounds are separate from archive retention. Validate an archive using
the lifecycle tool's `validate` action before restore rehearsal.

## Defaults and variables

```yaml
---
daybook_operations_api_backup_python: /home/daybook-operations/venv/bin/python
daybook_operations_api_backup_script: /home/daybook-operations/site/services/operations_api/lifecycle.py
daybook_operations_api_backup_config: /etc/daybook-operations/lifecycle.json
daybook_operations_api_backup_root: /opt/backups/daybook_operations
daybook_operations_api_backup_archive: ""
daybook_operations_api_backup_user: daybook-operations
# Optional registration through tasks_from: register_echoport.
daybook_operations_api_backup_runner: /usr/local/libexec/daybook-operations-backup
daybook_operations_api_backup_policy: /etc/daybook-operations-backup.json
daybook_operations_api_backup_staging: /var/lib/daybook-operations-backup
daybook_operations_api_backup_mc: /usr/local/bin/mc
daybook_operations_api_backup_alias: minio
daybook_operations_api_backup_bucket: backups
daybook_operations_api_backup_target: daybook_operations_api
daybook_operations_api_backup_fastdeploy_service: daybook-operations-backup
daybook_operations_api_backup_fastdeploy_root: /home/fastdeploy/site
daybook_operations_api_backup_echoport_root: /home/echoport/site
daybook_operations_api_backup_schedule: ""
daybook_operations_api_backup_update_schedule: false
daybook_operations_api_backup_retention_days: 30
```

## Validation

Local contract tests exercise disabled defaults, rendered units/plists and lifecycle
safety. The Daybook suite exercises real PostgreSQL concurrency and dump/restore,
HTTP delivery recovery and importer regression fixtures. Live deployment and
attended import/rollback validation remain required before production acceptance.

## Echoport registration

Include this role with `tasks_from: register_echoport` after the API, FastDeploy,
Echoport and root mc alias exist. The default schedule is empty for manual
validation. Set the schedule only after upload/restore and off-host replication
checks. Echoport owns scheduling and remote retention; no additional timer is
installed. Re-register at least every 90 days to renew the 180-day scoped token.
An existing target retains its schedule and active/paused/disabled state. To
change its schedule explicitly, also set `daybook_operations_api_backup_update_schedule: true`;
reactivation remains a separate attended Echoport action. Registration requires
live execution and rejects Ansible check mode before mutation.

The root-owned bridge in `/usr/local/libexec` accepts only backup requests for its
fixed target/bucket. It invokes application Python and reads source archives as
the service account, then uploads a root-private copy. It verifies the download
checksum before reporting success. The v1 lifecycle validator requires exactly
four archive members, which is the reported file count. Temporary copies are
removed on ordinary success/failure and handled SIGTERM/SIGINT. Each external command
has a 240-second limit (five commands, below the 1800-second Echoport limit).
A hard kill or host crash can leave private `echoport-*`/`upload-*` directories:
pause and drain the target, verify no bridge child remains, and remove only those
identified stale directories from the two configured roots. There is no automatic
sweep of uncertain work. Existing manual
lifecycle archives remain operator-managed. The root mc alias's credentials never
enter the service process, request context or output. Failed uploads may leave an
unreferenced remote object for operator inspection; the runner never deletes
remote objects on an ambiguous failure.

Restore requests are refused before backup commands. Download the exact archive
and use the attended lifecycle restore with quiesced clients and reconciliation.
Before deployment, credential rotation or a manual lifecycle operation, pause the
Echoport target and wait for its running backup to finish. Resume afterward. The
bridge lock prevents overlapping bridge runs, not other lifecycle operations.
