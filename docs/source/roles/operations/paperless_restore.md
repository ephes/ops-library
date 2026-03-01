# Paperless Restore Role

Restore Paperless-ngx from archives produced by `paperless_backup`.

## Capabilities

- Discovers archives (or accepts explicit paths) and validates checksums/metadata
- Optionally uploads archives from the controller if missing on host
- Creates safety snapshots before modifying data
- Supports both document importer restores and raw pg_dump/media rsync
- Reconciles SQL-restore ownership/privileges back to app owner for tables, views, materialized views, and sequences
- Drops/recreates PostgreSQL DB/user when requested
- Performs service orchestration and HTTP health checks, with rollback-on-failure logic
- Dry-run mode (`paperless_restore_dry_run: true`) for verification

## Usage

```yaml
- hosts: paperless
  roles:
    - role: local.ops_library.paperless_restore
      vars:
        paperless_restore_archive: latest
        paperless_restore_use_importer: true
        paperless_restore_passphrase: "{{ lookup('community.sops.sops', 'secrets/paperless.yml')['exporter_passphrase'] }}"
```

Refer to `roles/paperless_restore/README.md` for the full list of variables (safety snapshot paths, checksum toggles, fetch options, health-check URLs, etc.).

Operational note:

- SQL restore fallback uses admin DB connection vars (`paperless_restore_postgres_admin_*`), then normalizes ownership to `paperless` via reconciliation SQL.
