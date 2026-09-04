# tailscale_metrics_endpoint

Expose cached Tailscale login state and node-key expiry as an authenticated HTTP endpoint for Nyxmon `json-metrics` checks.

## Design

1. A root-owned systemd timer runs `tailscale status --json` through a small exporter.
2. The exporter writes cached JSON to `/var/lib/tailscale-metrics/tailscale.json`.
3. An unprivileged HTTP service serves the cached JSON at `/.well-known/tailscale` with basic auth.

This avoids SSH checks from Nyxmon while still alerting before a node reaches
`NeedsLogin`. It can also expose the node's live `Self.Online` state and an
optional IPv4 default-route probe, allowing a LAN-side monitor to diagnose a
node whose Tailscale path is unavailable.

The role targets Debian/Ubuntu hosts and installs `apache2-utils` for `htpasswd`.
When fail-closed IP-filter verification is enabled, it also installs the
distribution's `bpftool` provider (the running kernel's `linux-tools` package,
`linux-tools-common`, and the GA upgrade-tracking `linux-tools-generic`
metapackage on Ubuntu; `bpftool` on Debian). This keeps the fail-closed
service-start check available across upgrades on Ubuntu's GA kernel track. HWE
hosts must also keep their release-specific `linux-tools-generic-hwe-*`
metapackage installed, or rerun this role after changing kernel series or
rebooting into a newly installed HWE ABI.
The default deployment binds to a Tailscale IPv4 address; allow-listing is
limited to localhost and the Tailscale IPv4 CGNAT range (`100.64.0.0/10`). To
monitor a broken Tailscale path from the same LAN, bind to the host's specific
LAN address, add only the required LAN subnet to
`tailscale_metrics_endpoint_ip_address_allow`, and keep HTTP basic
authentication enabled. Use `0.0.0.0` only when multiple local addresses are
required. Every bind relies on systemd's cgroup-v2/BPF IP filter. Set
`tailscale_metrics_endpoint_require_effective_ip_filter: true` for every
non-Tailnet bind; the role then fails deployment unless both ingress and egress
programs are actually attached to the service cgroup. It defaults off so
existing Tailnet-only deployments remain compatible. The endpoint unit repeats
that check before every service start, including after reboot, and therefore
fails closed if a later kernel/systemd change removes the filters. A host-firewall rule
remains useful defense in depth for all non-Tailnet binds. The endpoint is plain HTTP, so a LAN
binding sends Basic Auth credentials without transport encryption; use a
credential dedicated to this read-only endpoint and keep the LAN allow-list as
narrow as possible.

The allow-list is replaced, not extended, when overridden; include `localhost`
and every Tailnet/LAN entry the endpoint must retain. Entries must be valid IP
addresses or networks, with IPv4 prefixes no broader than `/8` and IPv6
prefixes no broader than `/32`.

## Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `tailscale_metrics_endpoint_enabled` | `false` | Enable or disable the endpoint |
| `tailscale_metrics_endpoint_bind` | `{{ tailscale_ip \| default('127.0.0.1') }}` | Bind address; normally the host Tailscale IPv4 |
| `tailscale_metrics_endpoint_port` | `9107` | HTTP listen port |
| `tailscale_metrics_endpoint_path` | `/.well-known/tailscale` | Endpoint path |
| `tailscale_metrics_endpoint_ip_address_allow` | localhost and `100.64.0.0/10` | systemd IP traffic allow-list |
| `tailscale_metrics_endpoint_auth_user` | `CHANGE_ME` | Basic auth username |
| `tailscale_metrics_endpoint_auth_password` | `CHANGE_ME` | Basic auth password |
| `tailscale_metrics_endpoint_packages` | `python3`, `apache2-utils` | Runtime packages installed by the role |
| `tailscale_metrics_endpoint_warning_days` | `3` | Warning threshold for remaining key lifetime |
| `tailscale_metrics_endpoint_critical_days` | `1` | Critical threshold for remaining key lifetime |
| `tailscale_metrics_endpoint_ip_bin` | `/usr/sbin/ip` | `ip` executable used by the optional default-route probe |
| `tailscale_metrics_endpoint_bpftool_bin` | `/usr/sbin/bpftool` | `bpftool` executable used to fail closed when systemd's IP filter is ineffective |
| `tailscale_metrics_endpoint_require_effective_ip_filter` | `false` | Install verification tools and require effective ingress/egress cgroup IP filters; enable for non-Tailnet binds |
| `tailscale_metrics_endpoint_default_route_interface` | empty | Interface used by the optional IPv4 default-route probe |
| `tailscale_metrics_endpoint_require_default_ipv4_route` | `false` | Require a default IPv4 route on the configured interface |
| `tailscale_metrics_endpoint_require_self_online` | `false` | Include `Self.Online` in `summary.overall_ok`; defaults off for compatibility |
| `tailscale_metrics_endpoint_mdstat_path` | `/proc/mdstat` | Linux mdraid status file read by the optional RAID probe |
| `tailscale_metrics_endpoint_require_mdraid_healthy` | `false` | Require at least one active mdraid array and reject any member bitmap containing `_` |
| `tailscale_metrics_endpoint_required_mdraid_arrays` | `[]` | Array names that must be present when mdraid health is required |
| `tailscale_metrics_endpoint_timer_interval` | `300` | Service-relative target interval; the wall-clock backstop may trigger sooner |
| `tailscale_metrics_endpoint_timer_on_calendar` | `*:0/5` | Wall-clock backstop for the collector timer |

Allow-list CIDRs must use a nonzero prefix no larger than 32 for IPv4 or 128 for
IPv6. World-open prefixes are rejected during role validation.
The role argument specification also coerces timer intervals to integers and
route/self-online requirement flags to booleans at the role boundary.

### Collector timer arming

`OnBootSec=` and `OnUnitActiveSec=` are both monotonic triggers. Once the
one-shot boot trigger has fired, missing service activation history can leave
neither with a future elapse; systemd then parks the timer as `active
(elapsed)` with `NextElapseUSecMonotonic=infinity`. The collector never runs
again while the endpoint keeps serving the frozen payload, so every `summary`
assertion built on it stays green against a stale snapshot.

The timer therefore also carries `OnActiveSec=` (anchored on the timer unit's
own activation) and `OnCalendar=` (the only trigger type `Persistent=true`
applies to). Because `ansible.builtin.systemd: state: started` is a no-op on an
already-active timer and cannot repair a parked one, the role reads
`NextElapseUSecMonotonic` and `NextElapseUSecRealtime` after starting the timer,
restarts it when neither names a future trigger, and then asserts that the timer
is armed.

## Response Shape

```json
{
  "summary": {
    "backend_running": true,
    "self_online": true,
    "default_ipv4_route_present": true,
    "mdraid_healthy": true,
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
  "network": {
    "default_ipv4_route_required": true,
    "default_ipv4_route_interface": "enp1s0f1",
    "default_ipv4_route_present": true,
    "default_ipv4_route_detail": "default via 192.168.178.1 dev enp1s0f1"
  },
  "storage": {
    "mdraid_required": true,
    "mdraid_required_arrays": ["md0", "md1"],
    "mdraid_healthy": true,
    "mdraid_detail": "",
    "mdraid_arrays": [
      {
        "name": "md0",
        "level": "raid1",
        "status": "[UU]",
        "healthy": true
      }
    ]
  },
  "meta": {
    "age_seconds": 23
  }
}
```

Nyxmon should check `summary.backend_running`, `summary.self_online`,
`summary.default_ipv4_route_present`, `summary.key_expiry_warning_ok`,
`summary.key_expiry_critical_ok`, and `meta.age_seconds`. The ops-control
Tailscale deploy uses `meta.age_seconds < 900`, which allows three missed
300-second collector intervals before alerting on stale endpoint data.
When route probing is disabled, `summary.default_ipv4_route_present` is `true`
by definition; consumers that require route evidence must also deploy with
`tailscale_metrics_endpoint_require_default_ipv4_route: true`. `Self.Online` is
always reported, but only affects `summary.overall_ok` when
`tailscale_metrics_endpoint_require_self_online` is enabled.
Set `tailscale_metrics_endpoint_require_mdraid_healthy: true` on hosts backed
by Linux software RAID. The payload then exposes every active array under
`storage.mdraid_arrays`, sets `summary.mdraid_healthy`, and folds that signal
into `summary.overall_ok`. A missing `/proc/mdstat`, no active arrays, or a
member bitmap such as `[_U]` is unhealthy. Set
`tailscale_metrics_endpoint_required_mdraid_arrays` to the host's expected array
names when a wholly missing array must also fail the probe. Arrays reported as
`active (auto-read-only)`, such as an idle swap mirror, are included. Active
non-redundant personalities such as RAID0 and linear have no member bitmap;
they are reported with `status: null` and treated as assembled, while required
array names still detect their disappearance. When the probe is disabled,
`summary.mdraid_healthy` is `null` rather than an unevaluated all-clear.

## Validation

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://<TAILSCALE_IP>:9107/.well-known/tailscale
curl -sS -u "nyxmon:<password>" http://<TAILSCALE_IP>:9107/.well-known/tailscale | jq .

systemctl status tailscale-metrics-collector.timer
systemctl status tailscale-metrics-endpoint
```
