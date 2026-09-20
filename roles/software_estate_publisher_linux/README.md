# software_estate_publisher_linux

Host-local Linux/systemd inventory publisher. Reuses the weekly scheduler and
durable HTTPS sender from `software_estate/files`; installs no SSH credentials,
remote collection, Vector pipeline, Syft, package updates or privileged helper.
Requires systemd and Python 3.10+, and is intended for Debian-family hosts.

## Runtime and privileges

The `software-estate-publisher` system account has no login shell, sudo access or
Docker group. The oneshot service reads only metadata accessible to that account.
Unreadable application checkouts/virtualenvs and inaccessible Docker remain visible
as coverage gaps; deployment never relaxes application permissions to hide them.
Programs are immutable, root-owned releases. Configuration and the host-bound
writer are private files in `/etc/software-estate-publisher`; state and pending
reports are in `/var/lib/software-estate-publisher`. Only state is writable inside
the service sandbox. It uses `NoNewPrivileges`, no capabilities, a read-only system
and home directories, private temporary/devices namespaces and umask 0077. AF_NETLINK is permitted for
the resolver's local address-family discovery; it grants no network-admin capability.

The timer checks two minutes after boot and hourly at the configured minute, with
up to 90 seconds of jitter. Its persistent calendar trigger catches an elapsed
event after downtime. It does not wake the machine. The publisher itself persists
the seven-day cadence, so downtime produces one due scan rather than a scan for
each missed week. Pending delivery is attempted on every eligible tick. Each scan
and delivery phase has a 120-second deadline; systemd allows 300 seconds total.
Successful first deployment starts one tick immediately. There is no login
requirement on Linux and no automatic restart loop on rejection.

## Variables

All variables have prefix `software_estate_publisher_linux_`.

| Variable | Default | Meaning |
| --- | --- | --- |
| `state` | `present` | `absent` stops/disables service and timer and removes units only |
| `policy` | `{}` | Explicit local collector policy; must contain the receiver host ID |
| `hostnames` | `[]` | Allowed local short names, including the policy's logical host ID |
| `endpoint` | empty | Required HTTPS inventory endpoint |
| `writer` | empty | Host-bound credential; empty preserves an already installed writer |
| `minute` | `23` | Hourly calendar minute, integer 0–59 |
| `python` | `/usr/bin/python3` | Absolute system Python path without whitespace/metacharacters |

The fixed account, service name and paths isolate this publisher from other jobs.
Existing managed paths must have the expected owner and safe permissions, without
symlinks or hard links. This includes the code ancestors `/usr/local`,
`/usr/local/bin` and `/usr/local/lib`: this role deliberately refuses group-writable
ancestors, including Debian installations using `root:staff` mode 2775. That is an
explicit deployment precondition, not an instruction to silently chmod shared
system directories. Inspect those permissions before choosing a host; remediation
of shared ancestry requires its own operator decision. The role never changes these shared ancestors. Writer installation uses Ansible
`no_log` and disables
diff output. Supply the writer from an encrypted secret; never put it in a command
line. The role does not issue or rotate receiver credentials.

```yaml
- hosts: selected_linux_host
  become: true
  roles:
    - role: local.ops_library.software_estate_publisher_linux
      software_estate_publisher_linux_hostnames: [example]
      software_estate_publisher_linux_policy:
        host: example
        applications: []
      software_estate_publisher_linux_endpoint: https://inventory.example/v1/inventory
      software_estate_publisher_linux_writer: "{{ encrypted_inventory_writer }}"
```

Superseded root-owned code releases are retained for rollback and to avoid deleting
modules used by an in-flight interpreter. Releases live only under
`/usr/local/lib/software-estate-publisher/<content-hash>/`. They consume the size of
five Python source files per deployment change and are not pruned automatically.
For manual cleanup, stop both units and all manual callers, preserve the release
named in the installed service and wrapper, then remove only explicitly selected
older hash directories. Never include config, writer or state in code cleanup.

## Operation and removal

`systemctl status software-estate-publisher.timer` shows scheduling;
`journalctl -u software-estate-publisher.service` and the private `last-run.json`
show bounded outcomes without credentials or report bodies. Exit 75 means a
concurrent manual invocation holds the lock; the next tick retries. Exit 1 means
deferred/blocked delivery or an error, and 143 means an interrupted run.

The root-owned `/usr/local/bin/software-estate-publisher` wrapper drops to the
publisher account before executing. It accepts the same manual modes as the
macOS publisher (see `roles/software_estate_publisher/README.md`): `--check`, `--send-only`,
`--collect-now`, and explicit retry overrides. A normal call respects cadence.
`--check` validates local config/identity/permissions/cadence without scanning,
network access or server authentication. An offline receiver does not fail this
deployment gate. All modes use the same whole-run lock. The shared README also
documents clock
correction and corrupt-state recovery; substitute these Linux paths and run its
Python snippet as the publisher user while both timer and service are stopped.

Deploy with `state: absent` to stop/disable both units and remove their files.
Account, code, wrapper, config, writer, cadence and pending reports are retained;
the manual command still works. Reinstallation resumes the saved cadence and
queue. This is a delivery queue, not a separate backup service: successful reports
live in the receiver's protected history, and unconfirmed reports must be retained
locally across removal. A filesystem backup of this private state must preserve
ownership and must not be restored over a newer queue without reconciliation.

## Validation

Run `just test-software-estate`, `just typecheck`, repository lint/full tests, then
deploy to an explicitly selected inventory host. Verify actual service identity,
timer state, authenticated receiver download, no rescan on repeated activation,
and removal/reinstallation with a pending immutable report. Real sleep or reboot
requires a separate operator maintenance window; do not claim it from clock tests.
