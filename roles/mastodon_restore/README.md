# Mastodon Restore Role

Restores Mastodon from archives produced by `mastodon_backup`, including database, media, and configuration.

## Features

- Unpacks the archive into a staging directory (removed afterwards, also on failure).
- Validates the dump with `pg_restore --list` (it must contain `TABLE DATA`) and a full
  `pg_restore --file=/dev/null` read **before** any service is stopped.
- Stops the services and fails closed if a stop does not take.
- Takes safety copies before the first overwrite (see below), then drops and recreates the
  database and restores the dump with `--single-transaction`.
- Restores media, `.env.production`, systemd units, Traefik and nginx configuration when present.
- Runs migrations (and, for Takahe, optionally `collectstatic`) and starts the services.
- On any failure after the safety copies: restores the safety dump, the media snapshot and the
  config files, leaves the services **stopped** and fails with both safety paths.

## Safety copies

Each run writes a new UTC-timestamped set; nothing prunes them:

- `mastodon_restore_safety_root/<ts>/database/<db>.dump`: `pg_dump -Fc` of the live database,
  taken after the stop (skipped when the database does not exist yet, as on a rebuilt host).
  Needs free space for one compressed dump.
- `mastodon_restore_media_safety_root/<ts>`: snapshot of `mastodon_media_path` (local storage only). It is a
  hard-link copy (`cp -al`), so keep the root on the same filesystem as the media; on another
  filesystem the role falls back to a full copy, which needs space for the whole media tree.
  Media uploaded after the backup stays in this snapshot even though `rsync --delete` removes
  it from the live tree.
- `mastodon_restore_safety_root/<ts>/files/`: the env file, the systemd units the archive
  replaces, and the Traefik and nginx files as they were before the restore.

The paths are printed at the start and at the end of the run. Delete them once the restored
instance is verified.

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
| `mastodon_restore_cleanup` | `true` | Remove the staging directory (also after a failure). |
| `mastodon_restore_safety_root` | `/var/backups/mastodon-pre-restore` | Parent of the timestamped safety dump and config copies. |
| `mastodon_restore_media_safety_root` | `/home/mastodon/media-pre-restore` | Parent of the timestamped media snapshots (same filesystem as the media). |
| `mastodon_restore_postgres_become_user` | `postgres` | Postgres OS user for running restore commands. |

Restore keeps `mastodon_restore_postgres_become_user` defaulting to `postgres` so `dropdb`, `createdb`, and
`pg_restore` continue to work with peer-authenticated local PostgreSQL setups. The role makes the staged database
dump path traversable by that OS user before invoking `pg_restore`.

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
