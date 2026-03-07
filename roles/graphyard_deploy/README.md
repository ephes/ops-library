# graphyard_deploy

Deploys the core Graphyard Django application and runtime services (`graphyard-web`, `graphyard-agent`) on Ubuntu/Debian hosts.

## What This Role Does

- Creates/maintains the `graphyard` user and app directories.
- Deploys Graphyard source via `rsync` (default) or `git`.
- Creates a uv-managed virtual environment and syncs runtime dependencies.
- Renders `/etc/graphyard/graphyard.env`.
- Runs `manage.py migrate` and `manage.py collectstatic --noinput`.
- Optionally renders and applies declarative `MetricCollectionSpec` definitions.
- Renders and enables systemd units:
  - `graphyard-web.service`
  - `graphyard-agent.service`
- Verifies deploy health via `GET /v1/health` on localhost.

## Requirements

- Target host runs systemd.
- `uv_install` role is available in this collection.
- For `rsync` deploys, controller has local Graphyard source checkout.
- Secrets must be supplied by the caller (for example via SOPS in ops-control).

## Key Variables

| Variable | Default | Notes |
| --- | --- | --- |
| `graphyard_deploy_method` | `rsync` | `rsync` or `git` |
| `graphyard_source_path` | `""` | Required when using `rsync` |
| `graphyard_git_repo` | `https://github.com/ephes/graphyard.git` | Used for `git` deploy mode |
| `graphyard_git_version` | `main` | Branch/tag/commit for `git` mode |
| `graphyard_home` | `/opt/apps/graphyard` | Base path |
| `graphyard_site_path` | `{{ graphyard_home }}/site` | Project root on host |
| `graphyard_env_path` | `/etc/graphyard/graphyard.env` | Environment file consumed by systemd units |
| `graphyard_django_secret_key` | `CHANGEME` | Required, must be overridden |
| `graphyard_influx_token` | `CHANGEME` | Required when `graphyard_influx_token_required=true` |
| `graphyard_metric_collection_specs_apply` | `false` | Render/apply declarative metric specs via `manage.py apply_metric_collection_specs` |
| `graphyard_metric_collection_specs_prune` | `false` | Pass `--prune` so DB specs omitted from the rendered file are deleted by `name` |
| `graphyard_metric_collection_specs_path` | `/etc/graphyard/metric-collection-specs.json` | Rendered JSON file path for declarative specs |
| `graphyard_metric_collection_specs` | `[]` | Authoritative list of spec objects keyed by `name` |
| `graphyard_web_bind_host` | `127.0.0.1` | Web bind host |
| `graphyard_web_bind_port` | `8051` | Web bind port |
| `graphyard_web_workers` | `1` | Keep conservative for SQLite profile |
| `graphyard_healthcheck_enabled` | `true` | Enable post-deploy health verification |
| `graphyard_skip_django_manage` | `false` | Skip migrate/collectstatic in rollback workflows |

See `defaults/main.yml` for the full variable set.

## Example

```yaml
- name: Deploy Graphyard core app
  hosts: macmini
  become: true
  roles:
    - role: local.ops_library.graphyard_deploy
      vars:
        graphyard_deploy_method: rsync
        graphyard_source_path: /Users/jochen/projects/graphyard
        graphyard_django_secret_key: "{{ graphyard_secrets.django_secret_key }}"
        graphyard_influx_token: "{{ graphyard_secrets.influx_token }}"
        graphyard_django_allowed_hosts:
          - 127.0.0.1
          - localhost
          - graphyard.home.xn--wersdrfer-47a.de
        graphyard_django_csrf_trusted_origins:
          - https://graphyard.home.xn--wersdrfer-47a.de
        graphyard_grafana_base_url: https://grafana.home.xn--wersdrfer-47a.de
        graphyard_metric_collection_specs_apply: true
        graphyard_metric_collection_specs_prune: true
        graphyard_metric_collection_specs:
          - name: Home Assistant Environment Scan
            enabled: true
            spec_type: home_assistant_env_scan
            interval_seconds: 60
            config:
              base_url: http://macmini.local:10020
              access_token: "{{ homeassistant_secrets.api_token }}"
              host_id: homeassistant
              service_id: homeassistant
```

## Notes

- This role deploys only the Graphyard core app/runtime.
- Vector producer and Traefik ingress stay in separate roles:
  - `graphyard_vector_deploy`
  - `graphyard_ingress_deploy`
- Auth/bootstrap reconciliation remains in `graphyard_auth_bootstrap_deploy`.
- Declarative metric spec provisioning is keyed by spec `name`.
- Default behavior is create/update only; omitted specs are left untouched unless `graphyard_metric_collection_specs_prune: true`.
- Prune is intentionally opt-in because it deletes any existing `MetricCollectionSpec` row whose `name` is not present in the rendered file.
- The underlying management command refuses `--prune` when the desired file is empty, which protects against accidental full deletion from a broken render.
