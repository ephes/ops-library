# SnappyMail Restore Role

Restores the SnappyMail data directory from a backup archive or pre-extracted directory.

## Disposition

`snappymail_restore` is `ad-hoc only`. Echoport is the preferred operator path
for routine SnappyMail recovery work. This narrow mail-adjacent role remains
callable for manual exceptions and compatibility, but it is not the default
operator workflow and should not be treated as an auto-removal candidate.

## Variables

- `snappymail_restore_source` (required): Path to the archive (`.tar.gz` or `.tar.zst`) or directory.
- `snappymail_restore_clean`: Restore into a fresh directory (`true`, default) or merge into the
  live directory (`false`).
- `snappymail_data_dir`: Target data directory (from `snappymail_shared`).
- `snappymail_restore_staging_dir`: Where archives are unpacked first. Default
  `<parent of data dir>/.<data dir name>.restore-staging`.
- `snappymail_restore_safety_root`: Holds the rollback manifest. Default
  `/var/backups/snappymail-pre-restore`.
- `snappymail_restore_cleanup`: Remove the staging directory (also after a failure). Default `true`.

## Safety copies and rollback

- An archive is unpacked into the staging directory first and must contain the data directory's
  name at its top level. Before, it was unpacked straight over the live parent directory after
  the data directory had already been deleted, so a corrupt archive left an empty data directory.
- The live data directory is renamed to `<dir>.pre-restore-<UTC timestamp>` next to itself
  (with `snappymail_restore_clean: false` it is copied there instead, and the backup is merged
  into the live directory). A mount point is refused before anything moves.
- If copying the backup into place or fixing ownership fails, the old directory is moved back
  and the run fails with the outcome.
- A successful run keeps only its own pre-restore copy and deletes older ones; an old copy that is or contains a mount point is never deleted (the run logs it and keeps it); delete it once
  SnappyMail is verified.
- SnappyMail has no service of its own to stop. nginx and PHP-FPM keep running during the
  restore and are restarted at the end, as before.

## Notes

- Uses `unarchive` for tar archives; directory sources are copied with `cp -a` (no longer
  `synchronize`).
- Ownership is normalized to the SnappyMail user/group after restore.
