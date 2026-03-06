# graphyard_vector_deploy

Deploys [Vector](https://vector.dev/) on a host and configures it to push normalized host metrics to Graphyard `POST /v1/metrics`.

## Features

- Installs Vector from the official apt repository (`apt.vector.dev`)
- Collects host metrics (`filesystem`, `disk`, `cpu`, `memory`, `load`, `network`)
- Normalizes events to Graphyard ingest schema (`ts`, `host`, `metric`, `value`, optional `service`, `tags`)
- Uses resilient delivery settings:
  - disk buffering
  - fixed request concurrency (default `1`)
  - explicit HTTP timeout
  - explicit retry backoff + retry window
- Writes `/etc/vector/vector.yaml` with mode `0640` and group `vector` to avoid exposing the bearer token to other users
- Sends JSON list payloads to Graphyard ingest (Graphyard accepts lists of metric objects)
- Validates Vector config before service restart

## Required Variables

```yaml
graphyard_vector_enabled: true
graphyard_vector_ingest_url: "https://graphyard.example.com/v1/metrics"
graphyard_vector_ingest_token: "<bearer token>"
```

## Common Variables

```yaml
graphyard_vector_host_id: "macmini"
graphyard_vector_service_id: "host_metrics"
graphyard_vector_source_tag: "macmini-vector"
graphyard_vector_scrape_interval_secs: 60
graphyard_vector_request_concurrency: 1
graphyard_vector_batch_max_events: 50
graphyard_vector_batch_timeout_secs: 5
graphyard_vector_filesystem_mountpoint_excludes:
  - "/run/docker/netns/*"
  - "/var/lib/docker/*"

graphyard_vector_metric_prefixes:
  - filesystem_
  - disk_
  - memory_
  - cpu_
  - load
  - network_
```

See `defaults/main.yml` for full variable reference.

## Notes

- Sink healthcheck is disabled because Graphyard does not expose a dedicated Vector-compatible healthcheck endpoint for this sink.
- Batch defaults are tuned for lower ingest request pressure: `batch.max_events: 50`, `batch.timeout_secs: 5`.
- Request concurrency remains pinned to `1` for stable single-node ingest behavior.
- Filesystem mountpoint excludes are rendered only when the `filesystem` collector is enabled.

## Example Playbook

```yaml
- name: Deploy Vector producer for Graphyard
  hosts: macmini
  become: true
  vars:
    graphyard_secrets: "{{ lookup('community.sops.sops', playbook_dir + '/../secrets/prod/graphyard.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.graphyard_vector_deploy
      vars:
        graphyard_vector_enabled: true
        graphyard_vector_host_id: "macmini"
        graphyard_vector_service_id: "host_metrics"
        graphyard_vector_ingest_url: "http://127.0.0.1:8051/v1/metrics"
        graphyard_vector_ingest_token: "{{ graphyard_secrets.vector_ingest_token }}"
```

## Validation

```bash
# On target host
systemctl status vector
journalctl -u vector -n 100 --no-pager
vector validate /etc/vector/vector.yaml
```
