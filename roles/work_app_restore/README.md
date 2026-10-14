# Work App Restore Role

`work_app_restore` restores an archive produced by `work_app_backup`
(copy of `homelab_restore` without media/cache). It validates the checksum
manifest and metadata slug, requires `sqlite3`, stops `work-app` (aborting
if the stop fails), takes a safety snapshot of the stopped site directory,
removes stale SQLite journal files, restores the SQLite database, static files, `.env`,
systemd unit and Traefik config, runs `manage.py check --deploy` and
`showmigrations`, requires `PRAGMA integrity_check` to return exactly `ok`
(otherwise the run fails and the safety snapshot is kept), restarts the service and verifies
`/accounts/login/` over HTTP.

## Key variables

```yaml
work_app_restore_archive: latest     # or a file name / absolute path
work_app_restore_dry_run: false
work_app_restore_allow_version_mismatch: false
work_app_restore_restore_env: true
work_app_restore_create_safe_snapshot: true
work_app_restore_safe_snapshot_delete: false   # true deletes the pre-restore copy after success
```

## Pre-restore copy

Before anything is replaced the role copies the stopped site directory
(`/home/work/site` by default, including `db.sqlite3` and `.env`) to
`<work_app_site_path>.pre-restore-<timestamp>`, for example
`/home/work/site.pre-restore-20261014T153000` (host local time). The copy is kept after a
successful restore as well as after a failed one, and the final task reports
its path. Nothing prunes these copies: inspect them and delete old ones by
hand. Set `work_app_restore_safe_snapshot_delete: true` to delete the copy
after a successful restore instead.

## License

MIT
