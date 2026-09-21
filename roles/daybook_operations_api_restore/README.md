# daybook_operations_api_restore

Restore operations evidence and signing keys with services held stopped.

Requires an exact archive path, explicit confirmation, and all clients quiesced.
Validation verifies the exact member set, file types, bounds and checksums before
service changes. The role stops and disables both units across reboots; the unprivileged helper verifies that state, makes a safety backup and performs a
transactional pg_restore. Current database connection credentials are retained;
archive signing keys and profile evidence are restored. An application failure
attempts restoration of the safety copy. Services stay stopped in all cases.

Example:

```yaml
- role: local.ops_library.daybook_operations_api_restore
  vars:
    daybook_operations_api_restore_archive: /opt/backups/daybook_operations/EXACT.tar
    daybook_operations_api_restore_confirmed: true
    daybook_operations_api_restore_clients_quiesced: true
```

Verify journal/evidence correspondence, retain old signing keys and reconcile
credential rotation before enabling services/bindings again. Never roll back a
source ledger as part of API restore. This role intentionally cannot automatically
resume claims. See the control repository's attended restore/cutover runbook.

## Defaults and variables

```yaml
---
daybook_operations_api_restore_python: /home/daybook-operations/venv/bin/python
daybook_operations_api_restore_script: /home/daybook-operations/site/services/operations_api/lifecycle.py
daybook_operations_api_restore_config: /etc/daybook-operations/lifecycle.json
daybook_operations_api_restore_archive: ""
daybook_operations_api_restore_confirmed: false
daybook_operations_api_restore_clients_quiesced: false
daybook_operations_api_restore_user: daybook-operations
```

## Validation

Local contract tests exercise disabled defaults, rendered units/plists and lifecycle
safety. The Daybook suite exercises real PostgreSQL concurrency and dump/restore,
HTTP delivery recovery and importer regression fixtures. Live deployment and
attended import/rollback validation remain required before production acceptance.
