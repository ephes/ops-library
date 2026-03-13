# SnappyMail Restore Role

Restores the SnappyMail data directory from a backup archive or pre-extracted directory.

## Disposition

`snappymail_restore` is `ad-hoc only`. Echoport is the preferred operator path
for routine SnappyMail recovery work. This narrow mail-adjacent role remains
callable for manual exceptions and compatibility, but it is not the default
operator workflow and should not be treated as an auto-removal candidate.

## Variables

- `snappymail_restore_source` (required): Path to the archive (`.tar.gz` or `.tar.zst`) or directory.
- `snappymail_restore_clean`: Remove existing data before restore. Default `true`.
- `snappymail_data_dir`: Target data directory (from `snappymail_shared`).

## Notes

- Uses `unarchive` for tar archives; falls back to `synchronize` for directory sources.
- Ownership is normalized to the SnappyMail user/group after restore.
