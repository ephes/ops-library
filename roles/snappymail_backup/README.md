# SnappyMail Backup Role

Creates a lightweight archive of the SnappyMail data directory (config, address book, logs) without touching IMAP mail storage.

## Disposition

`snappymail_backup` is `ad-hoc only`. Echoport is the preferred operator path
for routine SnappyMail recovery work. This narrow mail-adjacent role remains
callable for manual exceptions and compatibility, but it is not the default
operator workflow and should not be treated as an auto-removal candidate.

## Variables

- `snappymail_data_dir` (from `snappymail_shared`): Data directory to snapshot.
- `snappymail_backup_root`: Destination directory for archives. Default `/mnt/cryptdata/backups/snappymail`.
- `snappymail_backup_prefix`: Archive prefix. Default `snappymail`.
- `snappymail_backup_archive_format`: `tar.gz` (default) or `tar.zst`.

## Notes

- Fails if the data directory is missing.
- With `snappymail_backup_stop_services: true`, nginx and PHP-FPM are stopped while the archive is written and restarted in an `always` section, so a failed archive step still restarts them. Units that were already stopped stay stopped.
- Produces an archive named `<prefix>-<timestamp>.<ext>` under `snappymail_backup_root`.
