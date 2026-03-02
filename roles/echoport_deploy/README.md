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

echoport_staging_db_refresh_enabled: false
echoport_staging_db_refresh_hour: "2"
echoport_staging_db_refresh_minute: "20"
echoport_staging_db_refresh_targets: []
echoport_staging_db_refresh_triggered_by: "staging-refresh-scheduler"
```

## Notes

- `echoport_allowed_path_prefixes` must be a non-empty list of absolute paths.
- In `ops-control` playbooks, list variables replace role defaults (they do not merge), so
  if overriding `echoport_allowed_path_prefixes`, provide the full intended list.
- Keep sensitive values in the private control repo (SOPS), not in this public role.

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
