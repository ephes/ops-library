# Takahe Backup Role

Creates on-host backups of the Takahe database, media, and configuration with an optional archive fetch to the controller.

## Features

- Runs `pg_dump` in custom format with compression.
- Rsyncs the media directory when using the local backend (`takahe_media_backend` empty or `local://`).
- Captures `.env`, systemd units, Traefik, and nginx configs.
- Generates a manifest for restore verification.

## Usage

```yaml
- hosts: takahe
  become: true
  roles:
    - role: local.ops_library.takahe_backup
      vars:
        takahe_backup_prefix: "manual"
        takahe_backup_fetch_local: true
```

## Key Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `takahe_backup_root` | `/opt/backups/takahe` | Remote backup root. |
| `takahe_backup_prefix` | `manual` | Prefix for backup directory/archive names. |
| `takahe_backup_stop_services` | `true` | Stop services during backup for consistency. The restart runs in an `always` section, so a failed dump or copy still restarts the units this role stopped; units that were already stopped stay stopped. |
| `takahe_backup_include_media` | `true` | Include local media directory. |
| `takahe_backup_fetch_local` | `true` | Fetch archive to the controller (the local copy is set to 0600). |
| `takahe_backup_retain` | `7` | Number of archives to retain. |

See `defaults/main.yml` and `roles/takahe_shared/defaults/main.yml` for the full reference.

## Dependencies

- `local.ops_library.takahe_shared`

## Testing

```bash
cd /path/to/ops-library
just test-role takahe_backup
```

## License

MIT

## Task credential handling

PostgreSQL CLI tasks use a temporary 0600 passfile owned by the executing database user in a unique 0700 directory, removed in an always block on success or failure. Only the PGPASSFILE path appears in the task environment. Empty passwords retain the existing libpq authentication fallback. Passfile passwords must not contain CR or LF; colons and backslashes are escaped. Restore SQL, rollback order and database connection options are unchanged.
