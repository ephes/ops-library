# tailscale_metrics_endpoint

Expose cached Tailscale login state and node-key expiry as an authenticated HTTP endpoint for Nyxmon `json-metrics` checks.

## Design

1. A root-owned systemd timer runs `tailscale status --json` through a small exporter.
2. The exporter writes cached JSON to `/var/lib/tailscale-metrics/tailscale.json`.
3. An unprivileged HTTP service serves the cached JSON at `/.well-known/tailscale` with basic auth.

This avoids SSH checks from Nyxmon while still alerting before a node reaches `NeedsLogin`.

The role targets Debian/Ubuntu hosts and installs `apache2-utils` for `htpasswd`. The default deployment binds to a Tailscale IPv4 address; allow-listing is limited to the Tailscale IPv4 CGNAT range (`100.64.0.0/10`).

## Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `tailscale_metrics_endpoint_enabled` | `false` | Enable or disable the endpoint |
| `tailscale_metrics_endpoint_bind` | `{{ tailscale_ip \| default('127.0.0.1') }}` | Bind address; normally the host Tailscale IPv4 |
| `tailscale_metrics_endpoint_port` | `9107` | HTTP listen port |
| `tailscale_metrics_endpoint_path` | `/.well-known/tailscale` | Endpoint path |
| `tailscale_metrics_endpoint_auth_user` | `CHANGE_ME` | Basic auth username |
| `tailscale_metrics_endpoint_auth_password` | `CHANGE_ME` | Basic auth password |
| `tailscale_metrics_endpoint_packages` | `python3`, `apache2-utils` | Runtime packages installed by the role |
| `tailscale_metrics_endpoint_warning_days` | `3` | Warning threshold for remaining key lifetime |
| `tailscale_metrics_endpoint_critical_days` | `1` | Critical threshold for remaining key lifetime |
| `tailscale_metrics_endpoint_timer_interval` | `300` | Collector interval in seconds |

## Response Shape

```json
{
  "summary": {
    "backend_running": true,
    "key_expiry_disabled": false,
    "key_expiry_warning_ok": true,
    "key_expiry_critical_ok": true,
    "overall_ok": true
  },
  "tailscale": {
    "backend_state": "Running",
    "self": {
      "key_expiry": "2026-11-21T06:20:51Z",
      "days_until_key_expiry": 179.9
    }
  },
  "meta": {
    "age_seconds": 23
  }
}
```

Nyxmon should check `summary.backend_running`, `summary.key_expiry_warning_ok`, `summary.key_expiry_critical_ok`, and `meta.age_seconds`. The ops-control Tailscale deploy uses `meta.age_seconds < 900`, which allows three missed 300-second collector intervals before alerting on stale endpoint data.

## Validation

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://<TAILSCALE_IP>:9107/.well-known/tailscale
curl -sS -u "nyxmon:<password>" http://<TAILSCALE_IP>:9107/.well-known/tailscale | jq .

systemctl status tailscale-metrics-collector.timer
systemctl status tailscale-metrics-endpoint
```
