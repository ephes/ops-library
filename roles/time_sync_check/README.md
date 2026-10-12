# Time sync check

Verify that a systemd host's clock is synchronized, and fail or warn clearly when
it is not. The role is a check only: it installs nothing, starts or restarts
nothing, and never touches time, timezone or NTP settings. Every run reports
`changed=0`, also in check mode.

It exists because a host clock that silently drifts (a host was once about two
hours off) breaks TLS, token expiry, log correlation and monitoring timestamps
long before anyone looks at the clock.

## What is checked

A small read-only script (`files/time_sync_status.py`, standard library only)
runs on the host and reports JSON. A problem is raised when:

- neither `chrony`/`chronyd` nor `systemd-timesyncd` is active;
- the kernel clock is not synchronized (`timedatectl show -p NTPSynchronized`
  says `no`);
- chrony reports `Not synchronised` (`chronyc -c tracking`);
- the offset measured by the active service (`chronyc -c tracking`, or
  `timedatectl timesync-status` for systemd-timesyncd) is above
  `time_sync_check_max_offset_seconds`;
- synchronization cannot be confirmed at all (no `timedatectl` answer and no
  chrony status);
- the host clock differs from the controller clock by more than
  `time_sync_check_controller_max_skew_seconds`. This independent comparison
  catches a host that reports itself synchronized but follows a wrong source.

A service that is synchronized but has not reported an offset yet (timesyncd
right after boot) is noted, not treated as a problem.

## Requirements

A Linux host with systemd and `python3`. No root is needed. The controller's own
clock must be correct for the controller comparison; set the threshold to `0`
to skip it.

## Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `time_sync_check_max_offset_seconds` | `1` | Largest acceptable absolute offset reported by the time service |
| `time_sync_check_controller_max_skew_seconds` | `30` | Largest acceptable difference to the controller clock (includes SSH latency); `0` disables the comparison |
| `time_sync_check_fail` | `true` | `true` fails the play on a problem; `false` prints a `WARNING:` line and continues |
| `time_sync_check_python` | `python3` | Interpreter used for the status script on the host |

## Result

The role sets `time_sync_check_result` for later tasks:

```yaml
ok: false
problems:
  - "clock offset +7212.500000s exceeds the allowed 1s"
notes: []
source: systemd-timesyncd        # chrony, systemd-timesyncd or null
kernel_synchronized: true        # true, false or null (unknown)
source_synchronized: null        # chrony's own view; null when unknown
offset_seconds: 7212.5
controller_skew_seconds: 0.0
epoch: 1760000000.12
```

A failure reads, for example:

```text
Time synchronization check FAILED on macmini: the system clock is not
synchronized (NTPSynchronized=no). This role only checks; it changed nothing.
Fix NTP on the host (chrony or systemd-timesyncd), then rerun.
```

## Usage

Include it from a host baseline or as a preflight step of a deploy play:

```yaml
- name: Host baseline
  hosts: all
  gather_facts: false
  roles:
    - role: local.ops_library.time_sync_check
```

Warn instead of failing, and act on the result yourself:

```yaml
- name: Check the clock without stopping the play
  ansible.builtin.include_role:
    name: local.ops_library.time_sync_check
  vars:
    time_sync_check_fail: false
    time_sync_check_max_offset_seconds: 0.5
```

The script also runs on its own, for a monitoring probe or a quick look on the
host. `--strict` makes it exit 1 when a problem is found:

```bash
python3 time_sync_status.py --max-offset 1 --strict
```

## Testing

```bash
just test-time-sync-check
just molecule-test time_sync_check
```
