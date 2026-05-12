# Mastodon Backup Role

Creates on-host backups of the Mastodon database, media, and configuration with an optional archive fetch to the controller.

## Features

- Runs `pg_dump` in custom format with compression.
- Rsyncs the local media directory when `mastodon_storage_driver: local`, excluding cache files by default.
- Captures `.env.production`, systemd units, Traefik config, and nginx config.
- Generates a manifest for restore verification.

## Usage

```yaml
- hosts: mastodon
  become: true
  roles:
    - role: local.ops_library.mastodon_backup
      vars:
        mastodon_backup_prefix: "manual"
        mastodon_backup_fetch_local: true
```

## Key Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `mastodon_backup_root` | `/opt/backups/mastodon` | Remote backup root. |
| `mastodon_backup_prefix` | `manual` | Prefix for backup directory/archive names. |
| `mastodon_backup_stop_services` | `true` | Stop services during backup for consistency. |
| `mastodon_backup_include_media` | `true` | Include local media directory. |
| `mastodon_backup_media_rsync_excludes` | `["/cache/***"]` | Rsync exclude patterns for local media backups. |
| `mastodon_backup_fetch_local` | `true` | Fetch archive to the controller. |
| `mastodon_backup_retain` | `7` | Number of archives to retain. |
| `mastodon_backup_postgres_become_user` | `{{ mastodon_backup_owner }}` | OS user for running `pg_dump`. |

Mastodon's `public/system/cache` tree contains remote media cache data that can be refetched, and on busy
instances it can consume many filesystem entries. The default media backup excludes that cache subtree while
still preserving local account and media attachment files.

By default, `pg_dump` runs as the backup directory owner so it can write into the root-owned backup tree while
authenticating to PostgreSQL as `mastodon_backup_postgres_user`. If `pg_hba.conf` requires peer auth, set
`mastodon_backup_postgres_become_user` to `postgres` and ensure the backup directory is writable by that user.

See `defaults/main.yml` and `roles/mastodon_shared/defaults/main.yml` for the full reference.

## Dependencies

- `local.ops_library.mastodon_shared`

## Testing

```bash
cd /path/to/ops-library
just test-role mastodon_backup
```

## License

MIT
