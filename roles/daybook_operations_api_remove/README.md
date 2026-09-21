# daybook_operations_api_remove

Remove operations service entry points while preserving durable evidence.

Explicit confirmation and quiesced clients are required. The role stops/disables
the two systemd services and removes their units and the private router. Database,
backups, credentials, source checkout and user are retained for recovery. There
is no destructive data-removal toggle in this version.

```yaml
- role: local.ops_library.daybook_operations_api_remove
  vars:
    daybook_operations_api_remove_confirmed: true
    daybook_operations_api_remove_clients_quiesced: true
```

Disable bindings, drain local journals and take a verified backup before removal.
Reinstall with the deployment role and preserved identities. Never treat removal
as authorization to rerun uncertain effects or reset a memo ledger.

## Defaults and variables

```yaml
---
daybook_operations_api_remove_confirmed: false
daybook_operations_api_remove_clients_quiesced: false
```

## Validation

Local contract tests exercise disabled defaults, rendered units/plists and lifecycle
safety. The Daybook suite exercises real PostgreSQL concurrency and dump/restore,
HTTP delivery recovery and importer regression fixtures. Live deployment and
attended import/rollback validation remain required before production acceptance.
