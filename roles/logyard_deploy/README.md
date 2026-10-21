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

`rsync` mode pushes `logyard_source_path` with `--delete`, minus
`logyard_rsync_excludes`. Its `.git` entry has no trailing slash, so git
metadata stays behind both for a normal clone, where `.git` is a directory, and
for a git worktree, where it is a file. rsync never deletes excluded paths on
the host, so a `.git` file that an earlier deploy copied to
`{{ logyard_site_path }}/.git` stays until it is removed by hand. The `git`
deploy method clones the repository and does not use these excludes.

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
- `units.<id>` (only for units listed in `logyard_health_units`)

### Producer unit state

Ingest freshness only tells you that logs *stopped arriving*, and it cannot say so
until the freshness window runs dry (15 minutes for the warning window, 60 for the
critical one). `logyard_health_units` reports systemd unit state directly, so a
dead log producer is detected on the next poll instead:

```yaml
logyard_health_units:
  - id: vector
    unit: vector.service
```

Each entry produces a `units.<id>` object:

```json
{
  "units": {
    "vector": {
      "unit": "vector.service",
      "exists": true,
      "load_state": "loaded",
      "active_state": "active",
      "sub_state": "running",
      "result": "success",
      "error": null
    }
  }
}
```

Notes:

- The key set is stable. If the `systemctl` probe itself fails or times out, every
  field is still present but set to `null` and `error` carries the detail. In that
  case `exists` is `null`, not `false` — a failed query means existence is unknown,
  not disproved. An `exists == true` assertion fails either way, which is intended.

- `id` is required and **must not contain a dot**, because monitoring check paths
  are dot-delimited — `units.vector.active_state` is addressable,
  `units.vector.service.active_state` would be ambiguous. There is no implicit
  fallback to the unit name, since unit names contain dots.
- `id` and `unit` must both be strings. YAML turns `id: yes` into a boolean, which
  is rejected rather than coerced into the key `"True"`.
- Entries that are malformed, missing `id`/`unit`, carry a dotted or duplicate
  `id`, or fail to parse are reported under `units_rejected` (present only when
  non-empty) rather than dropped. A misconfigured entry is then visible in the
  payload instead of silently monitoring nothing. Reasons: `invalid_base64`,
  `invalid_json`, `not_a_list`, `not_an_object`, `missing_unit`, `missing_id`,
  `id_contains_dot`, `duplicate_id`.
- The unit list reaches the service base64-encoded (`LOGYARD_HEALTH_UNITS_B64`).
  systemd resolves `%` specifiers and backslash escapes inside `Environment=`
  values, so a raw JSON payload could be silently corrupted.
- `exists` is derived from `LoadState`, not the exit code: `systemctl show` exits 0
  even for a unit that does not exist. Assert `exists == true` alongside
  `active_state == "active"` so a typo in the unit name fails loudly rather than
  silently reporting `inactive` forever.
- `units` is always present (possibly empty), so check paths have a stable shape.
- Unit state deliberately does **not** feed into the top-level `status` field.
  `status` describes Logyard's own ingest health; producer liveness is a separate
  signal with its own check.
- The endpoint runs as the unprivileged `logyard` user. `systemctl show` is a
  read-only query and needs no elevation.
- The default is `[]`, since the producer is not necessarily colocated with the
  Logyard server. Set it per host.

### HTTP server implementation (Python or Rust)

`logyard_health_impl` selects the health endpoint's HTTP server: `python` runs
`logyard_health_script_path` (the unit's `ExecStart=`), `rust` runs the pinned
`metrics-httpd` release (mode `logyard-health`) through the drop-in
`/etc/systemd/system/<service>.service.d/metrics-httpd-impl.conf`
([`metrics_httpd_switch`](../metrics_httpd_switch/README.md),
`rust/metrics-httpd/PLAN.md` section 7). The endpoint keeps its address, path,
payload, user and `LOGYARD_*` environment; the unit file and the Python script
stay as they are with either value.

| Variable | Default | Meaning |
| --- | --- | --- |
| `logyard_health_impl` | `{{ metrics_httpd_impl \| default('python') }}` | `python` or `rust`; override per host for a canary. |
| `metrics_httpd_impl` | (unset: `python`) | Fleet-wide default for every metrics-httpd endpoint. |
| `metrics_httpd_rust_version` / `metrics_httpd_rust_sha256` | (unset) | Pinned release and the sha256 of its archive. Required for `rust`; with `python` a set version is installed and checked ahead of the switch. |

With `rust` the binary runs `metrics-httpd logyard-health`, which reads the
same `LOGYARD_*` environment as the Python script. Before the drop-in is
written its `--check-config` must pass as `logyard_user` with exactly the
unit's `Environment=` lines (the unit has no other sandbox settings): an
invalid number, a non-IP bind address, a Loki URL that is not `http://` or a
`logyard_health_units` entry the payload would list under `units_rejected`
stops a switch to Rust. After the restart the deploy checks that the unit runs
the selected implementation and that `GET` on the health path answers 200 with
a JSON object holding `status`, then pins the version in
`/opt/metrics-httpd/.pins/<service>`. Switching back to `python` removes the
drop-in and restarts the Python script.

On macmini the endpoint is deployed by pyinfra (`ops-deploy`
`services/logyard`), which gets the same switch in its own slice; this role is
the Ansible path and the rollback engine of that service.

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

Set `logyard_ca_store_root` to the prepared per-container CA root to mount
replacement native trust stores; prepare with `container_ca_remediate` before
deploying and refresh after image/custom CA changes. The empty default leaves
image trust unchanged. Verify actual runtime TLS before claiming protection.
