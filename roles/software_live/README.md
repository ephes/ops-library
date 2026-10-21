# software_live

Install a read-only software collector and an authenticated, cached JSON endpoint
for Debian/Ubuntu systemd hosts. The same collector can run over SSH without
installation. It observes Traefik's configured executable and the actual MainPID
executable, compares hashes and versions with desired state and upstream, and
lists security upgrades available in the local APT indexes, including held updates.
It also observes the host OS lifecycle and PostgreSQL clusters, server version,
current minor release and end-of-life date.

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
    os:
      expected_id: ubuntu
      product: ubuntu
      desired_cycle: '24.04'
    postgresql:
      expected: true
      desired_major: '17'
      cluster: main
      port: 5432
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
Set `postgresql.expected: false` where PostgreSQL must be absent. On database
hosts, every additional cluster—including a stopped cluster with missing
binaries—is reported as unexpected. The server version comes from the verified
running postmaster executable referenced by its cluster PID file, so the hardened
collector needs no database login or credentials. OS identity comes from
`/etc/os-release`.
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

Traefik checks support stable numeric releases. OS and PostgreSQL lifecycle data
comes from endoflife.date and is cached for one day. A lifecycle lookup failure
warns without replacing the last successful cache. OS desired-cycle drift,
standard-support expiry and EOL are distinct issues. PostgreSQL desired-major
drift, an outdated minor release, EOL and additional clusters are distinct issues.
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
`summary.os_ok`, `summary.postgresql_ok`, `summary.traefik_ok`,
`summary.security_updates_ok` and `summary.apt_indexes_fresh` are warning checks.
Nyxmon's existing `json-metrics` executor can consume them. Optional
`tasks_from: nyxmon` upserts only the supplied checks using
`software_live_nyxmon_checks`, preserving unrelated checks. Schema version 2
adds the required OS and PostgreSQL observations and summary fields. Upgrading
from schema version 1 requires adding the `os` and `postgresql` policy mappings
shown above before deploying the role. Existing schema-1 state is deliberately
rejected as stale/invalid until the schema-2 collector completes successfully.

Use `software_live_remove` to stop/remove this monitoring component. State is
retained by default. Removal does not alter Traefik or package maintenance.

## Python or Rust (`software_live_impl`)

The programs can run as the Python file (default) or as the pinned Rust
release `software-live` of this repository (`rust/software-live/PLAN.md` 7.3).
The base units always render the Python commands; `impl: rust` adds drop-ins
that point them at the versioned binary.

| Variable | Default | Meaning |
| --- | --- | --- |
| `software_live_impl` | `python` | `python` or `rust`: what the production units run. |
| `software_live_rust_version` | `""` | Release, e.g. `0.1.0`; required for `rust` or the shadow. |
| `software_live_rust_sha256` | `{}` | sha256 of the release archive per variant: `{ubuntu24.04: <64 hex>, debian13: <64 hex>}`. |
| `software_live_rust_release_url` | GitHub release of `software-live-v<version>`, archive `…-x86_64-unknown-linux-gnu-<variant>.tar.gz` | Download URL. |
| `software_live_rust_local_archive` | `""` | Controller path of an archive instead of the download (development). |
| `software_live_rust_keep_versions` | `3` | Newest release directories kept on top of the pins and the live versions (at least 2). |
| `software_live_rust_shadow` | `false` | Shadow units next to the production units (below). |
| `software_live_shadow_port` / `software_live_shadow_on_calendar` | `9119` / `*:7/15` | Shadow endpoint port (loopback only) and shadow collector schedule. |

**Variants.** `software-live-apt` (the APT observation, a separate
GPL-3.0-or-later helper) links the distribution's libapt-pkg, so each release
has one archive per variant. The role reads `/etc/os-release`: Ubuntu 24.04 is
`ubuntu24.04`, Debian 13 is `debian13`; any other system fails an `impl: rust`
or shadow deploy before the switch changes anything.

**Install.** The internal role `rust_release_binary` installs the archive
(`software-live`, `software-live-apt`, `LICENSE`, `LICENSE.GPL-3.0`) into
`<software_live_install_dir>/releases/<version>/` (root:root 0755, never
modified in place, a different archive for an installed version fails the
run) and checks `--version`. The candidate is then validated by its versioned
path before anything points at it: `validate --config policy.json` and
`software-live-apt observe` (as root, read-only, must report `status: ok`).
A failure stops the play; the running units, the drop-ins and the installed
versions stay as they were.

**Switch.** With `impl: rust` the drop-ins
`/etc/systemd/system/software-live-endpoint.service.d/impl.conf` and
`/etc/systemd/system/software-live-collector.service.d/impl.conf` reset
`ExecStart=` (and the collector's `ExecStartPost=`) and run
`releases/<version>/software-live` with the same arguments; any change reloads
systemd and restarts the endpoint and the timer. After the initial collection
(which first waits for a collector run still in progress
to end, since that run executes the previous program) the role verifies the
running program (for about 30 s): the endpoint is
active and `/proc/<MainPID>/exe` is the versioned binary (Python: its command
line runs `software_live.py serve`), the collector exited 0 with the selected
program and rewrote `state.json`.

**Rollback.** `software_live_impl: python` removes the drop-ins and restarts
the units with Python before any Rust task runs, so a missing, broken or
refused release never blocks it (with the shadow on, a broken release still
fails the play, but only after the production units run Python again). Python
reads the state and caches the Rust program wrote. Emergency path on the
host: remove both `impl.conf` files, `systemctl daemon-reload`, restart
`software-live-endpoint.service`, start `software-live-collector.service`,
then set the inventory to `python` before the next deploy.

**Pins and prune.** Only after the verification the role moves the pins of
`rust_release_binary` in `releases/.pins/`: `software-live` names the version
the production units run (removed with `impl: python`), and
`software-live.previous` names the version that ran before it (the version
last verified live: the old pin, or the release the endpoint ran). So a
Rust-to-Rust rollback target is always installed: v1 live, switch to v2
(previous v1), back to v1 (previous v2), on to v3 (previous v1). Then old
releases are pruned: kept are the newest `software_live_rust_keep_versions`,
every pin, every previous pin, and every version the host ran or was
configured to run when the play started: the drop-ins, the shadow units,
systemd's loaded commands, and every process of the four units (for a
running collector every PID of its control group, so a collector run still
executing an older release and its `software-live-apt` child keep that
release). If any of that cannot be read (an unreadable drop-in, a path below
`releases/` that is not `<version>/<file>`, a running unit whose control
group or process executable cannot be resolved), nothing is pruned in that
play. A failed verification moves no pin and prunes nothing.

**Shadow.** `software_live_rust_shadow: true` installs, next to the untouched
production units, `software-live-shadow-collector.service`/`.timer` (the Rust
`collect --report-usage` into `<data_dir>/shadow/`, root:metrics 0750, with
its own caches and projection, at `*:7/15`) and
`software-live-shadow-endpoint.service` (the Rust endpoint on
`127.0.0.1:9119`, `IPAddressAllow=localhost` only, serving the production
`state.json` with the production credentials, configured in
`<config_dir>/shadow-endpoint.json`). The shadow's release is pinned as
`.pins/software-live-shadow` (no rollback pin). Turning the flag off stops
and removes the shadow units, their configuration, `<data_dir>/shadow` and
the shadow pin. Deploying with the shadow on and `impl: python` puts a release
in place ahead of a switch.

`nyxmon_checks.py` stays Python and is installed in every mode.

## Validation

`just test-software-live-impl` runs the switch (filters, templates, and
`ansible-playbook` runs against localhost with fake releases, `systemctl` and
`/proc`). `just test-software-live` exercises version/hash drift, OS/PostgreSQL lifecycle,
additional PostgreSQL clusters, PID races, lookup failures, APT security/hold
classification, freshness, HTTP authentication and check upserts.
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

## Optional local inventory metadata export

`software_live_inventory_export` defaults to `false`. Set it to `true` only after
an inventory reader group already exists (`software_live_inventory_group`, default
`software-estate-publisher`). The role creates the separate root-owned 0750
`/var/lib/software-estate-observations` directory with that read-only group.
No user is added to metrics, Docker or sudo groups, and no monitoring password is
shared. Unsafe existing directory ownership/modes or symlinks are refused.

An optional `ExecStartPost` on the **existing** observation job projects the just
written local state into `software-health.json` (root-owned 0640, atomic replace).
It runs no probes or network requests itself and retains the original observation
time. Only host/time, OS/PostgreSQL/Traefik verdicts and versions, bounded issue
codes, and APT security-count/index-freshness fields are allowed. Paths, process
IDs, credentials, arbitrary source fields and package lists are omitted.
Export failure is logged by exception type and does not fail the existing health
job or alter its endpoint response. The previous projection may remain; its
original timestamp expires independently. Disabling export stops future writes;
a retained projection is not fresh forever and can be removed deliberately.

The unprivileged inventory reader must reject wrong-host, malformed, future or
older-than-1800-second projections at collection. A received weekly inventory is
an observation at its source time, not a live monitoring query. The receiver must
label historical health evidence rather than refreshing its age on delivery.
An unknown APT observation or stale indexes never means zero security updates.
