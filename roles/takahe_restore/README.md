# Takahe Restore Role

Restores Takahe from archives produced by `takahe_backup`, including database, media, and configuration.

## Features

- Unpacks archive into a staging directory.
- Drops and recreates the PostgreSQL database, then restores the custom-format dump.
- Restores media, `.env`, systemd units, Traefik, and nginx configuration when present.
- Restarts services and optionally reruns migrations.

## Usage

```yaml
- hosts: takahe
  become: true
  roles:
    - role: local.ops_library.takahe_restore
      vars:
        takahe_restore_archive: latest
```

## Key Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `takahe_restore_root` | `/opt/backups/takahe` | Directory containing backup archives. |
| `takahe_restore_archive` | `latest` | Archive name or `latest`. |
| `takahe_restore_run_migrations` | `true` | Run migrations after restoring the database. |
| `takahe_restore_cleanup` | `true` | Remove staging directory after restore. |

See `defaults/main.yml` and `roles/takahe_shared/defaults/main.yml` for the full reference.

## Dependencies

- `local.ops_library.takahe_shared`

## Testing

```bash
cd /path/to/ops-library
just test-role takahe_restore
```

## License

MIT
