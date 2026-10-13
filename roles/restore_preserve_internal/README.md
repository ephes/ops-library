# restore_preserve_internal

Internal task library for quiesced restore targets. Callers include `tasks/main.yml`
with `restore_preserve_path` and `restore_preserve_empty` (default `true`).
Requires Linux `findmnt`, `cp`, `rsync` and Python 3 on the managed host.

Ordinary directories are atomically renamed into a reserved timestamped sibling.
Mount points and `restore_preserve_empty: false` use an independent `cp -a` copy,
verified with a checksum and metadata rsync dry run before any live content is
cleared. Space checks reserve 10% or 16 MiB extra, whichever is larger.
Nested mounts and symlink targets are refused. Callers must stop all writers;
this helper does not synchronize concurrent restores or application writes.

Copies use `<live-directory>.pre-restore-<UTC timestamp>-<random suffix>`.
No success, failure or subsequent restore removes these copies. The owner
inspects and prunes them by hand. Read-only `tasks/preflight.yml` checks mounts and copy space before writers stop;
preservation repeats those checks on quiesced state. `tasks/validate.yml`
refuses overlapping live/staging/source paths and mutation of retained copies.
The helper prints a marked JSON record containing the copy path and original apparent
size in bytes (collected before any rename) before clearing and exposes `restore_preserve_report` for the
caller's final report. A failed copy can leave an incomplete sibling for manual
inspection, but leaves live data untouched. Check mode initializes a placeholder report and does not preserve or clear.
