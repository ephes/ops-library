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
```

## License

MIT
