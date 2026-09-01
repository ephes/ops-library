# OS APT Maintenance Role

Install a host-local `systemd` timer/service that runs apt maintenance and records durable JSON state for monitoring.

## What It Does

This role deploys:

- `/usr/local/sbin/os-apt-maintenance`: a root-owned runner for `apt-get update`, `dist-upgrade`, `autoremove`, and `autoclean`.
- `os-apt-maintenance.service`: a root `oneshot` systemd service.
- `os-apt-maintenance.timer`: a persistent, jittered systemd timer.
- `/var/lib/os-apt-maintenance/state.json`: durable run state updated atomically even when apt fails.
- Optional `os-apt-maintenance-endpoint.service`: an authenticated HTTP endpoint for Nyxmon `json-metrics` checks.

The role is intentionally limited to OS package maintenance. It does not replace application dependency upgrades, product upgrades, or FastDeploy ad-hoc apt runners.

## Safety Defaults

- Automatic reboot is disabled by default.
- The timer uses `Persistent=true` so missed runs catch up after downtime.
- The timer includes `RandomizedDelaySec` to avoid synchronized apt runs.
- The runner uses a non-blocking lock file to prevent overlapping runs.
- A failed run still writes `state.json` and preserves the previous `last_success_at`.
- The runner stamps the endpoint-readable group and mode onto `state.json` itself,
  on every write. systemd skips `ExecStartPost=` when `ExecStart=` exits non-zero,
  so relying on the unit alone left a failed run's state file unreadable by the
  endpoint user and the endpoint answering HTTP 503 - hiding the failure it had
  just recorded. The unit's fix-up runs from `ExecStopPost=-` for the same reason.
- Package config prompts use `--force-confold`, so unattended runs keep existing local config files.

## Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `os_apt_maintenance_enabled` | `true` | Enable role deployment. |
| `os_apt_maintenance_host_id` | `{{ inventory_hostname }}` | Stable host identifier written to state JSON. |
| `os_apt_maintenance_state_dir` | `/var/lib/os-apt-maintenance` | State directory. |
| `os_apt_maintenance_state_file` | `{{ os_apt_maintenance_state_dir }}/state.json` | Durable state JSON path. |
| `os_apt_maintenance_update_cache` | `true` | Run `apt-get update`. |
| `os_apt_maintenance_dist_upgrade` | `true` | Run `apt-get -y dist-upgrade`. |
| `os_apt_maintenance_autoremove` | `true` | Run `apt-get -y autoremove`. |
| `os_apt_maintenance_autoclean` | `true` | Run `apt-get -y autoclean`. |
| `os_apt_maintenance_auto_reboot` | `false` | Reboot automatically after a successful run if `/var/run/reboot-required` exists. |
| `os_apt_maintenance_timer_on_calendar` | `*-*-* 04:00:00` | Timer schedule. |
| `os_apt_maintenance_timer_randomized_delay_sec` | `2h` | Timer jitter. |
| `os_apt_maintenance_timer_persistent` | `true` | Catch up missed timer runs after downtime. |
| `os_apt_maintenance_run_on_deploy` | `false` | Run the apt maintenance service during role deploy. |
| `os_apt_maintenance_run_on_first_deploy` | `false` | Run the apt maintenance service when the state file did not exist before this deploy. |
| `os_apt_maintenance_freshness_max_age_seconds` | `1209600` | Monitoring threshold for last successful run, default 14 days. |
| `os_apt_maintenance_endpoint_enabled` | `false` | Serve state JSON over authenticated HTTP. |
| `os_apt_maintenance_endpoint_user` | `metrics` | Local system user that serves the endpoint and reads state. |
| `os_apt_maintenance_endpoint_bind` | `{{ tailscale_ip | default('127.0.0.1') }}` | Endpoint bind address. |
| `os_apt_maintenance_endpoint_port` | `9106` | Endpoint port. |
| `os_apt_maintenance_endpoint_path` | `/.well-known/os-apt-maintenance` | Endpoint path. |
| `os_apt_maintenance_endpoint_auth_user` | `CHANGE_ME` | Basic auth username. Required when endpoint is enabled. |
| `os_apt_maintenance_endpoint_auth_password` | `CHANGE_ME` | Basic auth password. Required when endpoint is enabled. |

## Example

```yaml
- name: Deploy OS apt maintenance
  hosts: ubuntu_hosts
  become: true
  roles:
    - role: local.ops_library.os_apt_maintenance
      vars:
        os_apt_maintenance_host_id: "{{ inventory_hostname }}"
        os_apt_maintenance_timer_on_calendar: "Sun *-*-* 04:00:00"
        os_apt_maintenance_timer_randomized_delay_sec: "4h"
        os_apt_maintenance_auto_reboot: false
        os_apt_maintenance_endpoint_enabled: true
        os_apt_maintenance_endpoint_bind: "{{ tailscale_ip }}"
        os_apt_maintenance_endpoint_auth_user: nyxmon
        os_apt_maintenance_endpoint_auth_password: "{{ nyxmon_storage_metrics_password }}"
```

`os_apt_maintenance_endpoint_auth_user` is the HTTP Basic auth user, not the local system user.
The endpoint service runs as `os_apt_maintenance_endpoint_user`, which defaults to the shared
`metrics` account used by other monitoring endpoint roles.

In `ops-control`, production currently overrides the public role defaults to a weekly Sunday
timer and a wider jitter window:

```yaml
os_apt_maintenance_timer_on_calendar: "Sun *-*-* 04:00:00"
os_apt_maintenance_timer_randomized_delay_sec: "4h"
os_apt_maintenance_run_on_first_deploy: true
```

## State JSON Contract

The runner writes a stable JSON object with these important fields:

```json
{
  "schema_version": 1,
  "host_id": "macmini",
  "generated_at": "2026-05-05T04:00:00Z",
  "last_run_started_at": "2026-05-05T04:00:00Z",
  "last_run_finished_at": "2026-05-05T04:03:15Z",
  "last_success_at": "2026-05-05T04:03:15Z",
  "last_exit_code": 0,
  "last_status": "success",
  "last_error": null,
  "reboot_required": false,
  "auto_reboot_enabled": false,
  "steps": {
    "update_cache": {"attempted": true, "status": "success", "duration_seconds": 8.12},
    "dist_upgrade": {"attempted": true, "status": "success", "duration_seconds": 92.7},
    "autoremove": {"attempted": true, "status": "success", "duration_seconds": 5.4},
    "autoclean": {"attempted": true, "status": "success", "duration_seconds": 1.3}
  }
}
```

When the HTTP endpoint is enabled, it adds request-time `meta` and `summary` fields. Nyxmon should prefer:

- `$.summary.last_run_ok == true`
- `$.summary.last_success_fresh == true`
- `$.meta.state_file_fresh == true`
- `$.reboot_required == false` as warning or critical, depending on operator policy

The endpoint reports `$.reboot_required` live at request time, so a successful
operator reboot clears the monitoring warning immediately even if the durable
state file was last written before the reboot. The previous state-file value is
exposed as `$.meta.state_reboot_required` for debugging.

### How a required reboot is detected

Two independent signals, OR'd together, with the reason reported in
`$.reboot_required_details`:

| Signal | `reasons` entry | Source |
| --- | --- | --- |
| `/var/run/reboot-required` exists | `reboot_required_flag` | Ubuntu's `update-notifier-common` |
| A newer kernel than the running one is installed | `stale_kernel` | `dpkg-query` vs `uname -r` |

The marker file alone is **not** sufficient. It is created by
`update-notifier-common`, which Debian does not ship by default and which is
absent on some Ubuntu hosts too. On such a host the marker can never appear, so
a check asserting `$.reboot_required == false` stays confidently green while the
machine runs a kernel several releases behind the one installed - a false
negative indistinguishable from a healthy host.

This was observed in production: a Debian 12 host running a bullseye `5.10`
kernel with `6.1` installed, monitored as green for over two years.

The kernel comparison needs no extra package and behaves identically on Debian
and Ubuntu. It only counts packages in dpkg state `installed`, so a
removed-but-not-purged kernel left in `config-files` does not raise a false
alarm, and it fails closed to "no signal" if `dpkg-query` is unavailable rather
than erroring the run.

`$.reboot_required_details` additionally carries `running_kernel`,
`running_kernel_version` and `newest_installed_kernel` when the kernel signal
fires, so an operator can tell a pending-kernel reboot from a library-triggered
one without logging in.

The kernel comparison runs inside the maintenance run and is persisted in the
state file, so it is only re-evaluated on the timer's cadence. The endpoint
re-reads the marker file on every request and serves the persisted kernel
signal for as long as `uname -r` still matches the kernel that run observed.
A reboot into the newer kernel therefore clears both signals immediately,
while a reboot back into the old kernel keeps the warning. State files written
before this signal existed serve marker-only behaviour until the next run.

**Known limitations.**

- The comparison only sees kernels installed as dpkg packages. A host booting
  a kernel installed outside dpkg - a custom build, a vendor kernel that was
  not packaged - has no `linux-image-*` packages to compare against, so
  `stale_kernel` reports no signal. That is a deliberate fail-safe: reporting
  nothing is correct behaviour for "cannot tell", and it avoids inventing a
  false warning. But it does mean **absence of a kernel signal on such a host
  is not evidence the kernel is current**, and those hosts still depend on the
  marker file alone. Track them separately.
- The comparison has no notion of *why* an older kernel is running. A host
  deliberately pinned to an older packaged kernel (a GRUB default pointing at
  a known-good release while a newer one stays installed) reports
  `stale_kernel` on every run until the pin is lifted or the newer package is
  removed. The role does not offer an allow-list for this; the warning is the
  truthful statement that a newer kernel is installed and not running, and
  what to do about it is an operator decision.

During an active run, `$.summary.currently_running` is `true`. `last_run_ok` remains true while
the previous successful run is still fresh, so monitoring does not page during normal apt work.

## Validation

```bash
systemctl status os-apt-maintenance.timer
systemctl cat os-apt-maintenance.service os-apt-maintenance.timer
cat /var/lib/os-apt-maintenance/state.json | jq .
journalctl -u os-apt-maintenance.service -n 100 --no-pager

# Endpoint, when enabled
curl -sS -o /dev/null -w '%{http_code}\n' http://<TAILSCALE_IP>:9106/.well-known/os-apt-maintenance
curl -sS -u "nyxmon:<password>" http://<TAILSCALE_IP>:9106/.well-known/os-apt-maintenance | jq .
```

## Relationship To FastDeploy

`apt_upgrade_register` remains the FastDeploy manual/API path for operator-triggered apt upgrades. This role owns unattended host-local cadence and monitoring state. Both paths may coexist on the same host.

## Testing

```bash
cd /path/to/ops-library
just test-role os_apt_maintenance
just lint-role os_apt_maintenance
```
