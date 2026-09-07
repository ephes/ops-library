# software_live

Install a read-only software collector and an authenticated, cached JSON endpoint
for Debian/Ubuntu systemd hosts. The same collector can run over SSH without
installation. It observes Traefik's configured executable and the actual MainPID
executable, compares hashes and versions with desired state and upstream, and
lists security upgrades available in the local APT indexes, including held updates.

The role never runs apt update/upgrade, changes Traefik, or restarts applications.
The deployment installs Python/APT bindings and endpoint dependencies if missing.

## Configuration

```yaml
- role: local.ops_library.software_live
  software_live_bind: 100.64.0.10
  software_live_auth_user: monitor
  software_live_auth_password: "{{ vault_metrics_password }}"
  software_live_policy:
    host: example
    traefik:
      expected: true
      unit: traefik.service
      binary_path: /usr/local/bin/traefik
      desired_version: '3.7.9'
    apt_max_age_seconds: 172800
```

Set `expected: false` for hosts without Traefik. An unexpected installed/running
proxy is reported rather than ignored. A null desired version is reported as
unassigned policy, never as a match. No arbitrary service commands are supported.
See `defaults/main.yml` for all deployment defaults. The endpoint binds only to
IPv4 loopback or a Tailscale address; port 9110 and path
`/.well-known/software-live` are defaults. Authentication uses an htpasswd file,
not a password in process arguments. The collector has a root-owned policy and
read-only filesystem access except its private state directory; the HTTP process
runs as `metrics`. There is no remote command execution endpoint.

## Observation contract

The collector runs every 15 minutes, writes JSON atomically with root:metrics 0640
on success **and reported collection errors**, and checks upstream once a day.
A failed refresh is reported unknown; it does not renew old cache timestamps.
The endpoint computes freshness from the observation timestamp on every request.
Stale/malformed/missing evidence fails closed. `collect` returns success for a
valid report even when software needs attention; consumers inspect `summary`.

Version support is intentionally limited to Traefik stable numeric releases.
This is release drift detection, not a complete CVE/applicability scan. In
particular, a patched version alone does not prove configuration mitigations.

APT is inspected through python-apt without refreshing indexes. All newer trusted
Debian/Ubuntu security-origin versions are considered, including versions blocked
by holds/pinning. Index publication age is reported conservatively; old or missing
security Release metadata warns even if the last maintenance job succeeded.
Configure the age budget deliberately; do not interpret a cached report as proof
that there are no security releases newer than those indexes.

## Operations

```sh
/usr/local/lib/software-live/software_live.py collect --config /etc/software-live/policy.json
systemctl status software-live-collector.timer software-live-endpoint.service
```

`summary.observation_ok` and request-time `summary.fresh` are critical checks.
`summary.traefik_ok`, `summary.security_updates_ok` and
`summary.apt_indexes_fresh` are warning checks. Nyxmon's existing `json-metrics`
executor can consume them. Optional `tasks_from: nyxmon` upserts only the supplied
checks using `software_live_nyxmon_checks`, preserving unrelated checks.

Use `software_live_remove` to stop/remove this monitoring component. State is
retained by default. Removal does not alter Traefik or package maintenance.

## Validation

`just test-software-live` exercises version/hash drift, PID races, lookup failures,
APT security/hold classification, freshness, HTTP authentication and check upserts.
Use synthetic identifiers in public tests; operator inventory belongs downstream.

Configuration, data and program paths must be dedicated directory names containing
`software-live` directly under `/etc`, `/var/lib` or `/usr/local/lib`. This prevents
accidental ownership changes or removal of broad parent directories.

An upstream lookup failure keeps the latest release unknown and raises a version
warning while successful local collection remains healthy. Unexpected or deleted
process-image paths are hashed without execution and report drift warnings; their
running version is explicitly unknown (`null`), while installed evidence remains
available. Read failures and unstable observations remain critical. Running-process version probing pins an open
file descriptor and validates the process image before executing that descriptor,
so a process re-exec cannot redirect the root probe to a different image.
