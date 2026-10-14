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

## Retained pre-restore copies

Before replacing live data, the shared `restore_preserve_internal` tasks retain
a timestamped sibling. Ordinary directories are atomically renamed away; mount
points are copied with `cp -a` and verified by checksum and metadata before
emptying their contents. Insufficient space fails before live data changes.
Nested mounts and symlink targets are refused. Quiesce all writers and run only
one restore at a time; when service stopping is disabled, quiescing is the caller’s responsibility.

SnappyMail archives are extracted and validated in a private staging directory
under `{{ snappymail_data_dir | dirname }}/.snappymail-restore-*` first.
Staging is removed in `always`, including on failure. Mount and space checks
run before writers stop and are repeated during preservation. A failure before
live data is modified restarts units this run stopped, best-effort. After
preservation or partial replacement, services stay stopped for manual recovery. With
`snappymail_restore_clean: false`, the live directory is copied and kept in place
for an additive restore. nginx/PHP-FPM are stopped before preservation and
restarted after success. With `snappymail_restore_restart_services: false`,
quiesce these writers yourself before calling the role.

The final report prints the retained path and size in bytes. Restores **never
remove or prune these copies**, including on failure or a later restore. The
owner prunes old copies by hand after inspecting them. Exact path patterns:

- `{{ snappymail_data_dir }}.pre-restore-*`

Each `*` is a UTC timestamp plus a random suffix. Failed copy verification may
leave an incomplete sibling; inspect it manually. On failure, use the reported
copy to recover before starting services.
