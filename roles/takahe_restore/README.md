# Takahe Restore Role

Restores Takahe from archives produced by `takahe_backup`, including database, media, and configuration.

## Features

- Unpacks the archive into a staging directory (removed afterwards, also on failure).
- Validates the dump with `pg_restore --list` (it must contain `TABLE DATA`) and a full
  `pg_restore --file=/dev/null` read **before** any service is stopped.
- Stops the services and fails closed if a stop does not take.
- Takes safety copies before the first overwrite (see below), then drops and recreates the
  database and restores the dump with `--single-transaction`.
- Restores media, `.env`, systemd units, Traefik and nginx configuration when present.
- Runs migrations (and, for Takahe, optionally `collectstatic`) and starts the services.
- On any failure after the safety copies: restores the safety dump, the media snapshot and the
  config files, leaves the services **stopped** and fails with both safety paths.

## Safety copies

Each run writes a new UTC-timestamped set; nothing prunes them:

- `takahe_restore_safety_root/<ts>/database/<db>.dump`: `pg_dump -Fc` of the live database,
  taken after the stop (skipped when the database does not exist yet, as on a rebuilt host).
  Needs free space for one compressed dump.
- `takahe_restore_media_safety_root/<ts>`: snapshot of `takahe_media_root`. It is a
  hard-link copy (`cp -al`), so keep the root on the same filesystem as the media; on another
  filesystem the role falls back to a full copy, which needs space for the whole media tree.
  Media uploaded after the backup stays in this snapshot even though `rsync --delete` removes
  it from the live tree.
- `takahe_restore_safety_root/<ts>/files/`: the env file, the systemd units the archive
  replaces, and the Traefik and nginx files as they were before the restore.

The paths are printed at the start and at the end of the run. Delete them once the restored
instance is verified.

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
| `takahe_restore_cleanup` | `true` | Remove the staging directory (also after a failure). |
| `takahe_restore_safety_root` | `/var/backups/takahe-pre-restore` | Parent of the timestamped safety dump and config copies. |
| `takahe_restore_media_safety_root` | `/home/takahe/media-pre-restore` | Parent of the timestamped media snapshots (same filesystem as the media). |

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
