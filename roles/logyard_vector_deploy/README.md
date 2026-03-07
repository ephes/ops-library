# logyard_vector_deploy

Deploys Vector on a producer host and ships journald logs to Logyard/Loki.

## Features

- installs Vector from the official apt repository
- reads from journald first
- normalizes logs into a compact JSON payload
- keeps Loki labels low-cardinality and stable
- uses disk buffering and explicit retry settings
- validates `vector.yaml` before restart

## Required Variables

```yaml
logyard_vector_enabled: true
logyard_vector_ingest_endpoint: "https://logyard.home.xn--wersdrfer-47a.de"
```

## Default Label Set

The sink labels are:

- `host`
- `service`
- `source_type`
- `environment`
- `level`

`unit`, `pid`, and `syslog_identifier` stay in the JSON log payload instead of the Loki index.

## Common Variables

```yaml
logyard_vector_host_id: "macmini"
logyard_vector_environment: "prod"
logyard_vector_source_type: "journald"
logyard_vector_include_units: []
logyard_vector_exclude_units: []
logyard_vector_current_boot_only: false
```

## Example Playbook

```yaml
- hosts: macmini
  become: true
  roles:
    - role: local.ops_library.logyard_vector_deploy
      vars:
        logyard_vector_enabled: true
        logyard_vector_ingest_endpoint: "https://logyard.home.xn--wersdrfer-47a.de"
        logyard_vector_host_id: "macmini"
        logyard_vector_environment: "prod"
```

## Validation

```bash
systemctl status vector
journalctl -u vector -n 100 --no-pager
vector validate /etc/vector/vector.yaml
```
