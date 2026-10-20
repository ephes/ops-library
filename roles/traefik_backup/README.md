# traefik_backup

Backs up Traefik's file-provider route configs and, optionally, its ACME state.

- Sources:
  - `/etc/traefik/dynamic/` (the dynamic route configs, one file per service; when enabled, default on)
  - `/etc/traefik/acme/acme.json` (when enabled, default off)
- Target: `/opt/backups/traefik/<prefix>-<timestamp>/` with `dynamic/`, `acme/` and `metadata.yml`
- Archive: `<prefix>-<timestamp>.tar.gz` (optional, enabled by default)
- Perms: root:root; `dynamic/` keeps the source permissions, `acme.json` and the archive are `0600`;
  every run also sets older archives in the backup root (`*.tar`, `*.tar.*`, `*.tgz`) to `0600`
- Fetch: to `~/backups/traefik/` when `traefik_backup_fetch_local` is true (local copy `0600`)

The dynamic configs contain basic-auth hashes; the backup directory is `0700`.
`traefik_restore` restores only `acme.json`. To roll back a route config, copy the
file from the archive's `dynamic/` back by hand or redeploy the owning service.

Key vars:
- `traefik_backup_prefix` (default: `manual`)
- `traefik_backup_dynamic_dir` (default: `/etc/traefik/dynamic`)
- `traefik_backup_include_dynamic` (default: true) — the run fails when the directory is missing
- `traefik_backup_acme_path` (default: `/etc/traefik/acme/acme.json`)
- `traefik_backup_include_acme` (default: false) — set to true if you still want to back up acme.json
- `traefik_backup_create_archive` (default: true)
- `traefik_backup_fetch_local` (default: true)
