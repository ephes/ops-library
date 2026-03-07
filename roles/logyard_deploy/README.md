# logyard_deploy

Deploys the Logyard core platform on Ubuntu:

- Loki single-binary runtime in Docker Compose
- explicit Loki retention policy
- Grafana datasource + dashboard provisioning into the shared Graphyard Grafana instance
- local JSON health endpoint for Nyxmon health and ingest-freshness checks

## Features

- installs Docker Engine + Compose if needed
- supports `rsync` and `git` deploy methods for the lean `logyard` service repo
- runs Loki as `grafana/loki` with filesystem-backed TSDB storage
- enforces retention with Loki compactor (`retention_enabled: true`)
- creates a shared Docker network so Graphyard Grafana can query Loki by container name
- copies Logyard dashboard assets into the shared Grafana provisioning tree
- exposes `/.well-known/logyard` on loopback for Nyxmon-compatible JSON checks

## Required Variables

```yaml
logyard_enabled: true
logyard_deploy_method: rsync
logyard_source_path: "/Users/jochen/projects/logyard"
```

When `logyard_deploy_method` is `git`, set:

```yaml
logyard_git_repo: "https://github.com/ephes/logyard.git"
logyard_git_version: "main"
```

## Key Variables

```yaml
logyard_loki_image: "grafana/loki:3.5.11"
logyard_loki_host_port: 3101
logyard_retention_period: "336h"

logyard_grafana_enabled: true
logyard_grafana_container_name: "graphyard-grafana"
logyard_grafana_datasource_uid: "logyard-loki"
logyard_grafana_datasource_path: "/opt/apps/graphyard/site/deploy/grafana/provisioning/datasources/logyard.yaml"

logyard_health_enabled: true
logyard_health_port: 9105
logyard_health_path: "/.well-known/logyard"
logyard_health_selector: '{host="macmini",source_type="journald"}'
logyard_health_warning_window_seconds: 900
logyard_health_critical_window_seconds: 3600
```

See `defaults/main.yml` for the full variable set.

## Retention

This role expects retention to be a real product decision, not an operator afterthought.

Default:

- `logyard_retention_period: "336h"` (`14d`)

The rendered Loki config enables the compactor and retention deletion path.

## Shared Grafana Assumption

This role provisions its datasource and dashboard assets into the existing Graphyard Grafana tree.
It therefore assumes:

- Graphyard Grafana already exists on the target host
- container name matches `logyard_grafana_container_name`
- shared provisioning root is writable by the deployment role

## Health Endpoint Contract

The role installs a tiny JSON endpoint for Nyxmon at:

```text
http://127.0.0.1:9105/.well-known/logyard
```

Response shape includes:

- `status`
- `loki.ready`
- `ingest.warning_window_entries`
- `ingest.critical_window_entries`
- `ingest.warning_fresh`
- `ingest.critical_fresh`

## Example Playbook

```yaml
- hosts: macmini
  become: true
  roles:
    - role: local.ops_library.logyard_deploy
      vars:
        logyard_enabled: true
        logyard_deploy_method: rsync
        logyard_source_path: "/Users/jochen/projects/logyard"
        logyard_health_selector: '{host="macmini",source_type="journald"}'
```

## Validation

```bash
systemctl status logyard
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' | grep logyard-loki
curl -fsS http://127.0.0.1:3101/ready
curl -fsS http://127.0.0.1:9105/.well-known/logyard | jq .
```
