# storage_metrics_endpoint

Exposes storage metrics (ZFS pool and dataset capacity, snapshot-retained space,
SMART status, and ECC counters) as an authenticated HTTP endpoint. The HTTP
server runs on system Python 3 (no venv/uv).

## Design

This role implements privilege separation for storage monitoring:

1. **Root timer** (`storage-metrics-collector.timer`) runs the storage exporter script every 300s (configurable) and writes JSON atomically (temp file + rename) to `/var/lib/storage-metrics/storage.json`

2. **Unprivileged HTTP server** (`storage-metrics-endpoint.service`) reads the JSON file and serves it over HTTP with:
   - Basic auth (bcrypt-hashed htpasswd, file mode 0640)
   - Tailscale-only binding (see "Network Binding" below)
   - Staleness metadata (`meta.age_seconds`)

This design allows Nyxmon to use `json-metrics` checks over HTTP instead of SSH, avoiding root SSH access from the monitoring system.

## Network Binding

The HTTP server binds to a specific IP address, **not** `0.0.0.0`. By default it uses `{{ tailscale_ip }}` which must be set by the playbook.

**Recommended approach**: Dynamically fetch the Tailscale IP at deploy time:

```yaml
pre_tasks:
  - name: Get Tailscale IP address
    ansible.builtin.command: tailscale ip --4
    register: _tailscale_ip_result
    changed_when: false

  - name: Set tailscale_ip fact
    ansible.builtin.set_fact:
      tailscale_ip: "{{ _tailscale_ip_result.stdout | trim }}"

roles:
  - role: local.ops_library.storage_metrics_endpoint
    storage_metrics_endpoint_bind: "{{ tailscale_ip }}"
```

To verify the bind address after deployment:

```bash
ssh root@<host> "ss -tlnp 'sport = :9101'"
# Should show: LISTEN ... 100.x.x.x:9101 ... (Tailscale IP, NOT 0.0.0.0)
```

Additionally, the systemd unit includes `IPAddressAllow=100.64.0.0/10` which restricts connections to Tailscale CGNAT range even if the bind address were misconfigured.

## Requirements

- The `nyxmon_storage_exporter` role must be deployed first (provides `/usr/local/bin/nyxmon-storage-metrics`)
- Tailscale must be installed and connected
- System packages are installed via `storage_metrics_endpoint_packages` (defaults: `python3`, `apache2-utils`)

## Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `storage_metrics_endpoint_enabled` | `false` | Enable/disable the role |
| `storage_metrics_endpoint_bind` | `{{ tailscale_ip }}` | IP address to bind (use dynamic Tailscale IP) |
| `storage_metrics_endpoint_port` | `9101` | HTTP port |
| `storage_metrics_endpoint_path` | `/.well-known/storage` | Endpoint path |
| `storage_metrics_endpoint_auth_user` | `CHANGE_ME` | Basic auth username |
| `storage_metrics_endpoint_auth_password` | `CHANGE_ME` | Basic auth password (stored as bcrypt hash) |
| `storage_metrics_endpoint_packages` | `["python3", "apache2-utils"]` | System packages for the HTTP server |
| `storage_metrics_endpoint_timer_interval` | `300` | Service-relative target interval; the wall-clock backstop may trigger sooner |
| `storage_metrics_endpoint_timer_on_boot_sec` | `30` | Initial timer delay after boot |
| `storage_metrics_endpoint_timer_on_calendar` | `*:0/5` | Wall-clock backstop that keeps the collector scheduled after a late timer activation |
| `storage_metrics_endpoint_timer_randomized_delay_sec` | `30` | Jitter added to each timer run |

### Collector timer arming

The collector timer uses activation-relative, service-relative, and wall-clock
triggers. A consumed one-shot boot trigger combined with missing service
activation history can otherwise leave systemd with no next elapse, parking
the timer as `active (elapsed)` while the endpoint continues serving a frozen
file. The independent recurring anchors also recover safely from timer state
drift after delayed encrypted-storage startup.

After deployment the role inspects both systemd next-elapse properties,
restarts a parked timer, and fails unless either the monotonic or realtime
schedule is armed. `OnCalendar=` is also the wall-clock trigger to which
`Persistent=true` applies.

## Response Format

This role does not generate storage fields itself. It serves the complete JSON
document written by `nyxmon_storage_exporter`, including configured dataset
metrics.

Success (HTTP 200):

```json
{
  "disks": [...],
  "disks_by_name": {...},
  "ecc": {"ce": 0, "loaded": true, "ue": 0},
  "meta": {
    "age_seconds": 42,
    "generated_at": "2024-12-15T10:30:00+00:00",
    "generated_at_epoch": 1734260400,
    "served_at_epoch": 1734260442
  },
  "pools": {...},
  "zfs_datasets": [...],
  "zfs_datasets_by_name": {
    "timemachine": {
      "dataset": "fast/timemachine",
      "available_bytes": 412316860416,
      "used_by_snapshots_bytes": 274877906944,
      "ok": true
    }
  },
  "ts": 1734260400
}
```

**Meta fields explained:**
- `generated_at`: ISO timestamp derived from the JSON file's modification time (mtime)
- `generated_at_epoch`: Unix timestamp from file mtime (when collector last wrote the file)
- `served_at_epoch`: Unix timestamp when the HTTP response was generated
- `age_seconds`: `served_at_epoch - generated_at_epoch` (staleness indicator)

If `age_seconds` exceeds the timer interval significantly (e.g., >600 for a 300s timer), the collector may have failed.

**Error responses** (HTTP 502/503) return JSON:

```json
{
  "error": true,
  "error_type": "metrics_file_missing",
  "message": "Metrics file not found - timer may not have run yet"
}
```

Error types: `metrics_file_missing`, `invalid_json`, `read_error`, `not_found`

## Example Nyxmon Check

After deployment, configure a `json-metrics` check in Nyxmon:

```python
Check(
    name="Fractal Storage Health",
    check_type=CheckType.JSON_METRICS,
    url="http://fractal.tailde2ec.ts.net:9101/.well-known/storage",
    check_interval=300,
    data={
        "auth": {"username": "nyxmon", "password": "secret"},
        "checks": [
            {"path": "$.pools.fast.health", "op": "==", "value": "ONLINE", "severity": "critical"},
            {"path": "$.pools.tank.health", "op": "==", "value": "ONLINE", "severity": "critical"},
            {"path": "$.meta.age_seconds", "op": "<", "value": 600, "severity": "warning"},
        ],
    },
)
```

## HTTP server implementation (Python or Rust)

`storage_metrics_endpoint_impl` selects the HTTP server: `python` runs
`storage_metrics_endpoint_server_path` (the unit's `ExecStart=`), `rust` runs the
pinned `metrics-httpd` release through the drop-in
`/etc/systemd/system/<service>.service.d/metrics-httpd-impl.conf`
([`metrics_httpd_switch`](../metrics_httpd_switch/README.md),
`rust/metrics-httpd/PLAN.md` section 7). The endpoint keeps its path, port,
realm, htpasswd file, JSON file, user, sandbox and IP allow list; the unit file
and the Python script stay as they are with either value.

| Variable | Default | Meaning |
| --- | --- | --- |
| `storage_metrics_endpoint_impl` | `{{ metrics_httpd_impl \| default('python') }}` | `python` or `rust`; override per host for a canary. |
| `metrics_httpd_impl` | (unset: `python`) | Fleet-wide default for every metrics-httpd endpoint. |
| `metrics_httpd_rust_version` / `metrics_httpd_rust_sha256` | (unset) | Pinned release and the sha256 of its archive. Required for `rust`; with `python` a set version is installed and checked ahead of the switch. |

With `rust` the binary runs `json-file --bind --port --path --json-path
--htpasswd-file --realm storage-metrics --server-name storage-metrics-httpd/0.1`
from the variables above. Before the drop-in is written the binary's
`--check-config` must pass as `storage_metrics_endpoint_user` in the unit's sandbox;
after the restart the deploy checks that the unit runs the selected
implementation and that an unauthenticated request gets 401 with the realm,
then pins the version in `/opt/metrics-httpd/.pins/<service>`. Switching back
to `python` removes the drop-in and restarts the Python script.

## Validation

```bash
# Test endpoint (expect 401 without auth)
curl -sS -o /dev/null -w '%{http_code}\n' http://fractal.tailde2ec.ts.net:9101/.well-known/storage

# Test with auth (expect 200 + JSON)
curl -sS -u "nyxmon:password" http://fractal.tailde2ec.ts.net:9101/.well-known/storage | jq .

# Check timer status
systemctl status storage-metrics-collector.timer
systemctl show storage-metrics-collector.timer \
  -p SubState -p NextElapseUSecMonotonic -p NextElapseUSecRealtime
journalctl -u storage-metrics-collector.service --since "1 hour ago"

# Check HTTP server status
systemctl status storage-metrics-endpoint
```
