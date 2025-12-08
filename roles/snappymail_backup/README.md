# SnappyMail Backup Role

Creates a lightweight archive of the SnappyMail data directory (config, address book, logs) without touching IMAP mail storage.

## Variables

- `snappymail_data_dir` (from `snappymail_shared`): Data directory to snapshot.
- `snappymail_backup_root`: Destination directory for archives. Default `/mnt/cryptdata/backups/snappymail`.
- `snappymail_backup_prefix`: Archive prefix. Default `snappymail`.
- `snappymail_backup_archive_format`: `tar.gz` (default) or `tar.zst`.

## Notes

- Fails if the data directory is missing.
- Produces an archive named `<prefix>-<timestamp>.<ext>` under `snappymail_backup_root`.
