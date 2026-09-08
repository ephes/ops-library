# traefik_restore

Restores Traefik ACME state from a backup archive produced by `traefik_backup` (optional).

- Input: latest or specified archive under `/opt/backups/traefik` (or custom root)
- Restores: `acme.json` to `/etc/traefik/acme/acme.json` (when enabled)
- Perms: root:root, `0600`; directory created with `0700`
- Staging: `/tmp/traefik-restore` (cleared after restore)

Key vars:

- `traefik_restore_archive` (default: `latest`)
- `traefik_restore_root` (default: `/opt/backups/traefik`)
- `traefik_restore_acme_path` (default: `/etc/traefik/acme/acme.json`)
- `traefik_restore_include_acme` (default: false) — set to true if you need to restore acme.json

## Transaction-managed hosts

This legacy entry refuses hosts with `traefik_transaction_required: true` or an
existing `/var/lib/traefik-transactions` directory. Use reviewed Traefik recovery;
do not delete the journal or unset the guard to bypass an unresolved transaction.
