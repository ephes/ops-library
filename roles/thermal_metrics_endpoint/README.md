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
| `thermal_metrics_endpoint_timer_interval` | `300` | Service-relative target interval; the wall-clock backstop may trigger sooner |
| `thermal_metrics_endpoint_timer_on_boot_sec` | `30` | Delay after boot before first run |
| `thermal_metrics_endpoint_timer_on_calendar` | `*:0/5` | Wall-clock backstop that keeps the collector scheduled after a late timer activation |
| `thermal_metrics_endpoint_timer_randomized_delay_sec` | `30` | Per-run jitter |

See `defaults/main.yml` for the full path and service-name defaults.

### Collector timer arming

The collector timer combines `OnActiveSec=`, `OnUnitActiveSec=`, and
`OnCalendar=` with the boot trigger. If a one-shot boot trigger has already
been consumed and service activation history is unavailable, systemd can have
no next elapse and leave the timer `active (elapsed)` while the HTTP endpoint
keeps serving old sensor values. Independent recurring anchors also defend
against timer state drift after delayed encrypted-storage startup.

The role therefore checks the realtime and monotonic next-elapse properties,
restarts a parked timer, and fails deployment if systemd still has no future
trigger.

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

## HTTP server implementation (Python or Rust)

`thermal_metrics_endpoint_impl` selects the HTTP server: `python` runs
`thermal_metrics_endpoint_server_path` (the unit's `ExecStart=`), `rust` runs the
pinned `metrics-httpd` release through the drop-in
`/etc/systemd/system/<service>.service.d/metrics-httpd-impl.conf`
([`metrics_httpd_switch`](../metrics_httpd_switch/README.md),
`rust/metrics-httpd/PLAN.md` section 7). The endpoint keeps its path, port,
realm, htpasswd file, JSON file, user, sandbox and IP allow list; the unit file
and the Python script stay as they are with either value.

| Variable | Default | Meaning |
| --- | --- | --- |
| `thermal_metrics_endpoint_impl` | `{{ metrics_httpd_impl \| default('python') }}` | `python` or `rust`; override per host for a canary. |
| `metrics_httpd_impl` | (unset: `python`) | Fleet-wide default for every metrics-httpd endpoint. |
| `metrics_httpd_rust_version` / `metrics_httpd_rust_sha256` | (unset) | Pinned release and the sha256 of its archive. Required for `rust`; with `python` a set version is installed and checked ahead of the switch. |

With `rust` the binary runs `json-file --bind --port --path --json-path
--htpasswd-file --realm thermal-metrics --server-name thermal-metrics-httpd/0.1`
from the variables above. Before the drop-in is written the binary's
`--check-config` must pass as `thermal_metrics_endpoint_user` in the unit's sandbox;
after the restart the deploy checks that the unit runs the selected
implementation and that an unauthenticated request gets 401 with the realm,
then pins the version in `/opt/metrics-httpd/.pins/<service>`. Switching back
to `python` removes the drop-in and restarts the Python script.

## Validation

```bash
# Expect 401
curl -sS -o /dev/null -w '%{http_code}\n' http://fractal.tailde2ec.ts.net:9104/.well-known/thermal

# Expect 200 + JSON
curl -sS -u "nyxmon:<password>" http://fractal.tailde2ec.ts.net:9104/.well-known/thermal | jq .

systemctl status thermal-metrics-collector.timer
systemctl show thermal-metrics-collector.timer \
  -p SubState -p NextElapseUSecMonotonic -p NextElapseUSecRealtime
systemctl status thermal-metrics-endpoint
journalctl -u thermal-metrics-collector.service --since "1 hour ago"
```
