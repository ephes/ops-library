# SnappyMail Restore Role

Restores the SnappyMail data directory from a backup archive or pre-extracted directory.

## Variables

- `snappymail_restore_source` (required): Path to the archive (`.tar.gz` or `.tar.zst`) or directory.
- `snappymail_restore_clean`: Remove existing data before restore. Default `true`.
- `snappymail_data_dir`: Target data directory (from `snappymail_shared`).

## Notes

- Uses `unarchive` for tar archives; falls back to `synchronize` for directory sources.
- Ownership is normalized to the SnappyMail user/group after restore.
