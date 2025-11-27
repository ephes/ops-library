# traefik_backup

Backs up Traefik ACME state.

- Sources: `/etc/traefik/acme/acme.json` (required)
- Target: `/opt/backups/traefik/<prefix>-<timestamp>/acme/`
- Archive: `<prefix>-<timestamp>.tar.gz` (optional, enabled by default)
- Perms: root:root, `0600` for `acme.json`
- Fetch: to `~/backups/traefik/` when `traefik_backup_fetch_local` is true

Key vars:
- `traefik_backup_prefix` (default: `manual`)
- `traefik_backup_acme_path` (default: `/etc/traefik/acme/acme.json`)
- `traefik_backup_create_archive` (default: true)
- `traefik_backup_fetch_local` (default: true)
