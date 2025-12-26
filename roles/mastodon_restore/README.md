# Mastodon Restore Role

Restores Mastodon from archives produced by `mastodon_backup`, including database, media, and configuration.

## Features

- Unpacks archive into a staging directory.
- Drops and recreates the PostgreSQL database, then restores the custom-format dump.
- Restores media, `.env.production`, systemd units, Traefik configuration, and nginx configuration when present.
- Restarts services and optionally reruns migrations.

## Usage

```yaml
- hosts: mastodon
  become: true
  roles:
    - role: local.ops_library.mastodon_restore
      vars:
        mastodon_restore_archive: latest
```

## Key Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `mastodon_restore_root` | `/opt/backups/mastodon` | Directory containing backup archives. |
| `mastodon_restore_archive` | `latest` | Archive name or `latest`. |
| `mastodon_restore_run_migrations` | `true` | Run migrations after restoring the database. |
| `mastodon_restore_cleanup` | `true` | Remove staging directory after restore. |
| `mastodon_restore_postgres_become_user` | `postgres` | Postgres OS user for running restore commands. |

See `defaults/main.yml` and `roles/mastodon_shared/defaults/main.yml` for the full reference.

## Dependencies

- `local.ops_library.mastodon_shared`

## Testing

```bash
cd /path/to/ops-library
just test-role mastodon_restore
```

## License

MIT
