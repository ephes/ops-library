# Echoport Deploy Role

Deploys the Echoport Django application on a target host (production default: `macmini`).

The role installs/syncs source code, prepares the Python environment, runs migrations,
configures systemd + Traefik, and installs cron entries for backup scheduling, retention
cleanup, and optional staging DB refresh.

## Highlights

- Rsync-based deployment from a local source tree (`echoport_source_path`).
- Django env rendering with FastDeploy integration tokens.
- Backup path allowlist configurable via `echoport_allowed_path_prefixes`.
- Scheduler cron (`run_scheduled_backups`) and cleanup cron (`cleanup_old_backups`).
- Optional nightly `staging-db-refresh.sh` runner.

## Key Variables

### Required

```yaml
echoport_source_path: "/Users/you/projects/echoport"
echoport_django_secret_key: "..."
echoport_fastdeploy_base_url: "https://deploy.home.xn--wersdrfer-47a.de"
echoport_fastdeploy_service_token: "..."
```

### Important Defaults

```yaml
echoport_app_host: "127.0.0.1"
echoport_app_port: 10018
echoport_workers: 2

echoport_allowed_path_prefixes:
  - "/home/"
  - "/opt/"
  - "/var/lib/"
  - "/mnt/cryptdata/"

echoport_scheduler_enabled: true
echoport_scheduler_interval: "*/5"

echoport_cleanup_enabled: true
echoport_cleanup_hour: "3"
echoport_minio_mc_path: "/usr/local/bin/mc"
echoport_minio_alias: "minio"
echoport_minio_url: ""            # required when cleanup is enabled
echoport_minio_access_key: ""     # required when cleanup is enabled
echoport_minio_secret_key: ""     # required when cleanup is enabled
echoport_minio_verify_bucket: "backups"

echoport_staging_db_refresh_enabled: false
echoport_staging_db_refresh_hour: "2"
echoport_staging_db_refresh_minute: "20"
echoport_staging_db_refresh_targets: []
echoport_staging_db_refresh_triggered_by: "staging-refresh-scheduler"

# Optional; rendered into .env only when set (empty keeps Echoport's default)
echoport_stale_run_grace_seconds: ""       # ECHOPORT_STALE_RUN_GRACE_SECONDS, default 900
echoport_late_result_window_seconds: ""    # ECHOPORT_LATE_RESULT_WINDOW_SECONDS, default 86400
echoport_health_overdue_grace_minutes: ""  # ECHOPORT_HEALTH_OVERDUE_GRACE_MINUTES, default 60
```

## Notes

- The optional timing settings must be empty or non-negative whole numbers.
  `echoport_stale_run_grace_seconds` is how long a pending/running run may
  outlive its target timeout before it is reaped; `echoport_late_result_window_seconds`
  is how long a timed-out backup is checked for a late result;
  `echoport_health_overdue_grace_minutes` is how long after a cron time a target
  without a successful run is reported overdue.

- `echoport_allowed_path_prefixes` must be a non-empty list of absolute paths.
- In `ops-control` playbooks, list variables replace role defaults (they do not merge), so
  if overriding `echoport_allowed_path_prefixes`, provide the full intended list.
- Keep sensitive values in the private control repo (SOPS), not in this public role.
- The retention cleanup cron runs `cleanup_old_backups` as `echoport_user` and
  deletes expired archives with `mc`, so that user needs its own `mc` alias.
  When `echoport_cleanup_enabled` is true the role requires
  `echoport_minio_url`, `echoport_minio_access_key` and
  `echoport_minio_secret_key`, configures the alias for `echoport_user`
  (idempotently, only when URL or credentials differ), verifies it can list
  `echoport_minio_verify_bucket`, and writes `MINIO_MC_PATH` / `MINIO_ALIAS`
  into the application `.env`. Without this alias every scheduled deletion
  fails and `mc` reports a missing local path; check
  `/home/echoport/logs/cleanup.log` for `Complete with errors`.

## Example

```yaml
- hosts: macmini
  become: true
  roles:
    - role: local.ops_library.echoport_deploy
      vars:
        echoport_source_path: "/Users/jochen/projects/echoport"
        echoport_django_secret_key: "{{ echoport_secrets.django_secret_key }}"
        echoport_fastdeploy_base_url: "{{ echoport_secrets.fastdeploy_base_url }}"
        echoport_fastdeploy_service_token: "{{ echoport_secrets.fastdeploy_service_token }}"
        echoport_traefik_host: "echoport.home.xn--wersdrfer-47a.de"
```

## Restart behavior

Source and dependency changes notify the existing restart handlers after deployment.
Echoport restarts its systemd service. Unchanged syncs do not request a restart.
The `echoport_service_restart_on_change` setting (default `true`) controls these handlers.
