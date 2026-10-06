# Work App Shared Role

Shared defaults and shared facts for the work app lifecycle roles
(`work_app_deploy`, `work_app_backup`, `work_app_restore`, `work_app_remove`).
Modelled on `homelab_shared`.

## Current role surface

- Shared defaults in `defaults/main.yml` (user `work`, site `/home/work/site`,
  SQLite at `/home/work/site/db.sqlite3`, gunicorn on `127.0.0.1:10011`,
  systemd unit `work-app`, Traefik file `/etc/traefik/dynamic/work-app.yml`,
  backup root `/opt/backups/work_app`)
- Exports the `work_app_paths` fact from `tasks/main.yml`

Operators normally do not call this role directly; the lifecycle roles depend on it.

## License

MIT
