# Work App Backup Role

`work_app_backup` snapshots the work app's SQLite database (hot `sqlite3
.backup`, offline copy as fallback), static files, `.env`, systemd unit and
Traefik config into `/opt/backups/work_app/<prefix>-<timestamp>`, writes
`metadata.yml` and a SHA256 manifest, creates a tarball and fetches it to
`~/backups/work_app` on the controller. The offline fallback only copies the
database after `work-app` stopped successfully. It is a copy of `homelab_backup`
without the media/cache parts the work app does not have.

Scheduled backups go through Echoport (generic `echoport-backup` runner,
target `work_app`), like Homelab. This role backs `just backup work_app`.

## Key variables

```yaml
work_app_backup_prefix: manual
work_app_backup_root: /opt/backups/work_app
work_app_backup_include_static: true
work_app_backup_include_env: true
work_app_backup_include_systemd: true
work_app_backup_include_traefik: true
work_app_backup_force_stop: false
work_app_backup_fetch_local: true
```

Requires `sqlite3` and `rsync` on the target host.

## License

MIT
