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
```

## Validation

Local contract tests exercise disabled defaults, rendered units/plists and lifecycle
safety. The Daybook suite exercises real PostgreSQL concurrency and dump/restore,
HTTP delivery recovery and importer regression fixtures. Live deployment and
attended import/rollback validation remain required before production acceptance.
