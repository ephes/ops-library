# backup_metrics_endpoint

Expose Fractal backup-health signals as an authenticated HTTP endpoint for Nyxmon `json-metrics` checks.

## What It Does

This role deploys two components:

1. `backup-metrics-collector.timer` runs every `backup_metrics_endpoint_timer_interval` seconds.
2. `backup-metrics-endpoint.service` serves the collected JSON at `/.well-known/backup` (configurable).

The collector gathers:
- systemd timer/service state for backup jobs (`sanoid`, local `syncoid`, USB `syncoid`)
- latest snapshot recency for configured local replica datasets
- latest snapshot recency for USB datasets (when USB pool is imported)
- USB pool/device context (enabled/imported/device-present)

The endpoint adds staleness metadata (`meta.age_seconds`) based on JSON file mtime.
When quiet-hours skipping is enabled, the collector reuses cached local snapshot
metadata and updates `age_seconds`/`age_hours` without issuing fresh `zfs list`
probes against sleeping replica pools.

## Design

- Collection runs as root (needs `systemctl`, `zfs`, `zpool` visibility).
- HTTP server runs as unprivileged `metrics` user.
- Basic auth via htpasswd.
- Tailscale-only access by default (`IPAddressAllow=100.64.0.0/10` + explicit bind IP).

## Variables

### Core

| Variable | Default | Description |
|----------|---------|-------------|
| `backup_metrics_endpoint_enabled` | `false` | Enable/disable role |
| `backup_metrics_endpoint_bind` | `{{ tailscale_ip \| default('127.0.0.1') }}` | Bind address |
| `backup_metrics_endpoint_port` | `9103` | Listen port |
| `backup_metrics_endpoint_path` | `/.well-known/backup` | Endpoint path |
| `backup_metrics_endpoint_auth_user` | `CHANGE_ME` | Basic auth user |
| `backup_metrics_endpoint_auth_password` | `CHANGE_ME` | Basic auth password |
| `backup_metrics_endpoint_timer_interval` | `300` | Collector interval in seconds |
| `backup_metrics_endpoint_timer_on_boot_sec` | `30` | Initial timer delay after boot |
| `backup_metrics_endpoint_timer_randomized_delay_sec` | `15` | Jitter added to each timer run |
| `backup_metrics_endpoint_zfs_timeout` | `45` | Timeout per `zfs list` probe |
| `backup_metrics_endpoint_zfs_retries` | `1` | Retry count for probe timeouts |
| `backup_metrics_endpoint_zfs_retry_delay` | `2` | Delay between timeout retries (seconds) |
| `backup_metrics_endpoint_quiet_hours_enabled` | `false` | Enable quiet-hours mode |
| `backup_metrics_endpoint_quiet_hours_start` | `"06:00"` | Quiet-hours window start (`HH:MM`, local host time) |
| `backup_metrics_endpoint_quiet_hours_end` | `"22:00"` | Quiet-hours window end (`HH:MM`, local host time) |
| `backup_metrics_endpoint_quiet_hours_skip_local_snapshot_probes` | `true` | Reuse cached local snapshot data during quiet hours |

### Backup Signals

| Variable | Default | Description |
|----------|---------|-------------|
| `backup_metrics_endpoint_units` | sane defaults for sanoid/syncoid units | systemd units to report |
| `backup_metrics_endpoint_local_datasets` | `tank/replica/fast/{general,timemachine}` | local replica datasets to check |
| `backup_metrics_endpoint_usb_enabled` | `false` | whether USB offsite is expected |
| `backup_metrics_endpoint_usb_pool` | `vault` | USB pool name |
| `backup_metrics_endpoint_usb_device` | `""` | optional `/dev/disk/by-id/...` path |
| `backup_metrics_endpoint_usb_datasets` | `vault/...` defaults | USB replica datasets to check |

## Example

```yaml
- role: local.ops_library.backup_metrics_endpoint
  vars:
    backup_metrics_endpoint_enabled: true
    backup_metrics_endpoint_bind: "{{ tailscale_ip }}"
    backup_metrics_endpoint_auth_user: nyxmon
    backup_metrics_endpoint_auth_password: "{{ nyxmon_secrets.nyxmon_storage_metrics_password }}"
    backup_metrics_endpoint_usb_enabled: true
    backup_metrics_endpoint_usb_pool: vault
    backup_metrics_endpoint_local_datasets:
      - tank/replica/fast/general
      - tank/replica/fast/timemachine
    backup_metrics_endpoint_usb_datasets:
      - vault/replica/fast/general
      - vault/replica/fast/timemachine
      - vault/photos
      - vault/videos
      - vault/backups
```

## Response Shape (abridged)

```json
{
  "generated_at": "2026-02-17T06:00:00+00:00",
  "quiet_hours": {
    "enabled": true,
    "active": true,
    "skip_local_snapshot_probes": true
  },
  "snapshots": {
    "local": [{
      "dataset": "tank/replica/fast/general",
      "ok": true,
      "age_hours": 2.1,
      "probe_attempts": 0,
      "probe_retries_used": 0,
      "probe_skipped": true,
      "probe_skip_reason": "quiet_hours",
      "source": "cache"
    }],
    "usb": [{"dataset": "vault/replica/fast/general", "ok": null, "error": "usb_pool_not_imported"}]
  },
  "summary": {
    "required_units_ok": true,
    "local_snapshots_ok": true,
    "usb_snapshots_ok": null,
    "usb_state": "offline",
    "usb_pool_offline": true,
    "overall_ok": true
  },
  "units": {
    "sanoid": {"ok": true, "timer": {"active_state": "active"}, "service": {"result": "success"}}
  },
  "usb": {"enabled": true, "pool": "vault", "pool_imported": false, "state": "offline"}
}
```

## Validation

```bash
# 401 without auth (expected)
curl -sS -o /dev/null -w '%{http_code}\n' "http://<TAILSCALE_IP>:9103/.well-known/backup"

# 200 with auth
curl -sS -u "nyxmon:<password>" "http://<TAILSCALE_IP>:9103/.well-known/backup" | jq .

systemctl status backup-metrics-collector.timer
systemctl status backup-metrics-endpoint
journalctl -u backup-metrics-collector.service --since "1 hour ago"
```
