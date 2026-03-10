# thermal_metrics_endpoint

Expose cached thermal and fan metrics as an authenticated HTTP endpoint.

## Design

This role mirrors the existing storage-endpoint pattern:

1. a root-owned systemd timer runs `thermal_metrics_exporter` every
   `thermal_metrics_endpoint_timer_interval` seconds and writes JSON atomically
2. an unprivileged HTTP service reads that cached JSON and adds staleness
   metadata under `meta.*`
3. Graphyard or other internal consumers read the endpoint over Tailscale with
   basic auth

This keeps local `ipmitool` access on the monitored host instead of pushing BMC
credentials or IPMI-over-LAN into the central collector.

## Requirements

- `thermal_metrics_exporter` must already be deployed
- Tailscale installed and connected
- system packages from `thermal_metrics_endpoint_packages`

## Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `thermal_metrics_endpoint_enabled` | `false` | Enable or disable the endpoint |
| `thermal_metrics_endpoint_bind` | `{{ tailscale_ip }}` | Bind address; use the host Tailscale IP |
| `thermal_metrics_endpoint_port` | `9104` | HTTP listen port |
| `thermal_metrics_endpoint_path` | `/.well-known/thermal` | Endpoint path |
| `thermal_metrics_endpoint_auth_user` | `CHANGE_ME` | Basic auth username |
| `thermal_metrics_endpoint_auth_password` | `CHANGE_ME` | Basic auth password |
| `thermal_metrics_endpoint_timer_interval` | `300` | Collector interval in seconds |
| `thermal_metrics_endpoint_timer_on_boot_sec` | `30` | Delay after boot before first run |
| `thermal_metrics_endpoint_timer_randomized_delay_sec` | `30` | Per-run jitter |

See `defaults/main.yml` for the full path and service-name defaults.

## Response shape

The endpoint returns the exporter payload plus:

```json
{
  "meta": {
    "generated_at": "2026-03-10T13:20:00+00:00",
    "generated_at_epoch": 1773148800,
    "served_at_epoch": 1773148823,
    "age_seconds": 23
  }
}
```

If the metrics file is missing or invalid, the endpoint returns a JSON error
payload with HTTP `502` or `503`.

## Validation

```bash
# Expect 401
curl -sS -o /dev/null -w '%{http_code}\n' http://fractal.tailde2ec.ts.net:9104/.well-known/thermal

# Expect 200 + JSON
curl -sS -u "nyxmon:<password>" http://fractal.tailde2ec.ts.net:9104/.well-known/thermal | jq .

systemctl status thermal-metrics-collector.timer
systemctl status thermal-metrics-endpoint
journalctl -u thermal-metrics-collector.service --since "1 hour ago"
```
