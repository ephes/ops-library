# storage_metrics_endpoint

Exposes storage metrics (ZFS pool health, SMART status, ECC counters) as an authenticated HTTP endpoint.

## Design

This role implements privilege separation for storage monitoring:

1. **Root timer** (`storage-metrics-collector.timer`) runs the storage exporter script every 300s (configurable) and writes JSON to `/var/lib/storage-metrics/storage.json`

2. **Unprivileged HTTP server** (`storage-metrics-endpoint.service`) reads the JSON file and serves it over HTTP with:
   - Basic auth (htpasswd)
   - Tailscale/LAN binding (IPAddressAllow=100.64.0.0/10)
   - Staleness metadata (`meta.age_seconds`)

This design allows Nyxmon to use `json-metrics` checks over HTTP instead of SSH, avoiding root SSH access from the monitoring system.

## Requirements

- The `nyxmon_storage_exporter` role must be deployed first (provides `/usr/local/bin/nyxmon-storage-metrics`)
- Python 3
- apache2-utils (for htpasswd)

## Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `storage_metrics_endpoint_enabled` | `false` | Enable/disable the role |
| `storage_metrics_endpoint_bind` | `{{ tailscale_ip }}` | IP address to bind |
| `storage_metrics_endpoint_port` | `9101` | HTTP port |
| `storage_metrics_endpoint_path` | `/.well-known/storage` | Endpoint path |
| `storage_metrics_endpoint_auth_user` | `CHANGE_ME` | Basic auth username |
| `storage_metrics_endpoint_auth_password` | `CHANGE_ME` | Basic auth password |
| `storage_metrics_endpoint_timer_interval` | `300` | Seconds between metrics collection |

## Response Format

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
  "ts": 1734260400
}
```

The `meta.age_seconds` field indicates staleness - if this exceeds the timer interval significantly, the collector may have failed.

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

## Validation

```bash
# Test endpoint (expect 401 without auth)
curl -sS -o /dev/null -w '%{http_code}\n' http://fractal.tailde2ec.ts.net:9101/.well-known/storage

# Test with auth (expect 200 + JSON)
curl -sS -u "nyxmon:password" http://fractal.tailde2ec.ts.net:9101/.well-known/storage | jq .

# Check timer status
systemctl status storage-metrics-collector.timer
journalctl -u storage-metrics-collector.service --since "1 hour ago"

# Check HTTP server status
systemctl status storage-metrics-endpoint
```
