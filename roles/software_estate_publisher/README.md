# software_estate_publisher

Host-local macOS user LaunchAgent for the software-estate push publisher. Deploy
as the logged-in, unprivileged user, either locally or through an explicitly
invoked operator SSH connection. The runtime scans only that target Mac and sends
HTTPS; it does not acquire SSH access, poll other machines, install Syft or updates.
Path validation uses the target's discovered Python interpreter rather than the
controller's interpreter path. A user GUI domain must already exist on the target.
The original `software_estate` installation role and Vector services are unchanged.

## Behavior

At login/bootstrap and hourly at minute 17, run one bounded tick. The tick scans
only when seven days have passed since the last published scan (or no scan has
been published). Ten missed weeks produce one scan, not ten. A report containing
category errors still completes that scan attempt; it remains incomplete in the
receiver. A failed scan with no report remains due for the next hourly tick.

`StartCalendarInterval` coalesces missed sleeping-machine events on wake;
`RunAtLoad` checks again when the user logs in after power-off. It does not wake a
machine or run before user login. See [Apple's scheduling documentation](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/ScheduledJobs.html).

The tick always attempts eligible pending delivery, even when a scan fails or
cannot fit in the bounded outbox. The sender retains its existing hourly backoff,
permanent-rejection blocking and TLS/acknowledgement contract. Each scan and
sending phase has a 120-second deadline. The job exits instead of keeping a daemon
alive. `last-run.json` records bounded outcome data without report content or
credentials; launchd stdout/stderr go to `/dev/null` to avoid unbounded logs.
Check launchd's exit status too: unsafe configuration/state can fail before a new
result is written. Exit 1 means blocked/deferred delivery or local/scan failure;
exit 75 means another invocation holds the lock (retry next hourly tick); exit 143
means an operator stopped it. Deployment waits up to five minutes for a busy check
instead of treating contention as invalid configuration.

`.publisher.json` persists the host, last scan attempt that published a report and
last check. Backward clock movement over five minutes, malformed state and a
changed host fail closed. Forward clock jumps can make one scan due. A crash
between report publication and its schedule checkpoint can leave an extra report
and cause another scan next tick; existing reports remain immutable and retained.
No missing acknowledgement makes an old report fresh. Never edit reports or reset
schedule/delivery state simply to clear a failure.

The outer `.lock` in the state directory covers the whole tick. The outbox lock
separately protects publishing/retiring reports. Manual publisher calls use the
same outer lock. Legacy caller wrappers must acquire this lock too; the raw
collector/emitter are lower-level tools and do not coordinate a whole scan.
SIGTERM unwinds probe cleanup and releases locks. Publication/checkpoint writes
and acknowledgements use private atomic, fsynced files.

## Variables

| Variable (`software_estate_publisher_` prefix) | Default | Meaning |
| --- | --- | --- |
| `state` | `present` | `absent` disables/unloads and removes only the LaunchAgent |
| `home` | current user's home | Must equal the local Ansible user's home |
| `label` | `local.ops.software-estate` | LaunchAgent label |
| `program` | `~/.local/share/software-estate-publisher` | Private versioned code and stable `run` wrapper |
| `directory` | `~/.local/state/software-estate/publisher` | Private state/outbox; share with manual collector |
| `config` | `<program>/config.json` | Private configuration, credential path only |
| `plist` | `~/Library/LaunchAgents/<label>.plist` | Unmanaged-by-chezmoi job file |
| `python` | `/opt/homebrew/bin/python3` | Trusted Python 3.10+ interpreter |
| `minute` | `17` | Hourly calendar minute (0–59) |
| `policy` | `{}` | Required local collector policy with host and application probes |
| `hostnames` | `[]` | Required lowercase local short hostnames; observed hostname must match at installation and collection |
| `endpoint` | empty | Required HTTPS inventory endpoint |
| `credential_file` | empty | Private host-bound writer path; writer content is never embedded in runtime config or rotated |
| `writer` | empty | Optional secret for initial provisioning only; existing credential file is preserved |

Only use paths below the current home. Existing managed paths must be private,
owned by this user and not symlinks; regular managed files must not have hard links.
Credential path and parent are checked before any writes, using the same private
ownership/link constraints as managed publisher paths. Supply `writer` from an
encrypted secret only; whitespace-only values count as empty. Its copy task is
`no_log`, diff-disabled and `force: false`:
it provisions a missing file but never replaces an existing writer, even when the
supplied value differs. Explicit rotation/reconciliation is a separate operator
action. With empty `writer`, a private credential must already exist. Removal
needs neither a supplied writer nor an existing credential path.
Use a dedicated credential subdirectory below home; do not put the writer directly
in home or reuse a shared 0755 parent such as `~/.config`. Existing credential
parents must already be private; the role refuses them rather than changing a
shared directory's permissions. Intermediate ancestors are checked for symlinks;
only managed paths and the immediate credential parent have ownership/mode checks.
Use trusted, non-writable-by-other-users ancestors, as for other private state.
The credential has the same private-path requirements as `send.py`. Versioned
program directories prevent updating a running interpreter's imported modules.
The launchd environment explicitly includes Homebrew's path. Existing chezmoi
managed job paths must be configured through their source instead of this role.

```yaml
- hosts: localhost
  connection: local
  become: false
  roles:
    - role: local.ops_library.software_estate_publisher
      software_estate_publisher_hostnames: [workstation]
      software_estate_publisher_policy:
        host: workstation
        applications: []
        application_roots: [/Applications, /System/Applications]
      software_estate_publisher_endpoint: https://inventory.example/v1/inventory
      software_estate_publisher_credential_file: /Users/operator/.config/inventory/writer
```

## Manual operation and removal

Run `<program>/run` for an ordinary due/retry tick, `--collect-now` for a manual
scan that advances the cadence, or `--send-only` without collecting. With those
explicit manual modes, `--retry-now` and `--retry-blocked` retain the sender's
operator recovery semantics. `--check` validates configuration/state without
network or a scan. Do not put retry overrides in launchd's scheduled command.

Deploy again with `state: absent` to disable triggers, wait for unload and remove
only the plist. Code releases, `run`, configuration, credential, schedule, reports
and delivery state are retained. The retained manual command can still send;
stop using it if removal is intended to suspend all delivery. Reinstalling reuses
state, so it does not reset the weekly clock. Unload failure refuses removal.
No unconfirmed report is deleted by installation, update or removal.

## Recovery after a clock correction or host change

A backward correction exceeding five minutes needs operator investigation. Confirm
the current system clock is correct first. If only `last_check` was ahead by less
than the time you can wait, leave state intact: normal checks resume once time
catches up. For a larger, confirmed clock correction, remove the job using
`state: absent` and stop all manual callers. Save a private backup and re-anchor
the scheduler as below, substituting the configured program and state directory.
This conservatively preserves the elapsed scan age at the last check; it does not
scan, send, alter reports, or reset delivery backoff.

```python
# Run with the same configured Python interpreter, while the job is unloaded.
import json
import os
import sys
import time
from pathlib import Path

program = Path.home() / ".local/share/software-estate-publisher"
# Use the immutable directory containing publish.py, named in program/run.
release = Path("/absolute/path/from/program/run")
sys.path.insert(0, str(release))
import publish

config = publish.configuration(program / "config.json")
directory = config["directory"]
with publish.outbox.locked(directory):
    raw = json.loads(publish.outbox.private_read(directory / publish.STATE, 4096))
    now = time.time()
    state = publish.read_state(directory, config["policy"]["host"],
                               max(now, raw["last_check"]))
    if state["last_check"] <= now + 300:
        raise SystemExit("No backward-clock recovery needed")
    backup = directory / f"publisher-before-clock-recovery-{time.time_ns()}.json"
    descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(json.dumps(state).encode())
    correction = now - state["last_check"]
    if state["last_scan"] is not None:
        state["last_scan"] += correction
        if not publish.timestamp(state["last_scan"]):
            raise SystemExit("Invalid corrected scan time; original state retained")
    state["last_check"] = now
    publish.atomic_json(directory, publish.STATE, state)
```

Run `run --check`, then redeploy `state: present`. Sender retry deadlines retain
their original timestamps; if the clock correction leaves a retry far in the
future, inspect the reports and deliberately use `run --send-only --retry-now`.
Do not override a permanently blocked report without resolving its rejection.

A hostname alias change with the same logical receiver host requires updating
`hostnames`, retaining `policy.host` in that list. If `policy.host` was changed by
mistake, restore it; never relabel existing state or reports. An intentional new
receiver identity needs its own enrollment, writer credential and fresh state
directory, while the old directory and its unsent reports remain preserved for
resolution under the old identity. For corrupt state, restore a known-good private
scheduler backup after stopping callers, or use a fresh directory and preserve
the damaged directory for investigation; do not delete an outbox to repair cadence.

## Verification

`just test-software-estate`, `just typecheck`, required repository validation and
a live local install/run/remove/reinstall verify the contract. Tests cover cadence,
restart/wake catch-up, transient failure/retry, deadline, full outbox, corrupt
state, clock reversal, category failures and locks. Physical sleep/power-cycle
behavior still needs observation on the target; deterministic clock tests and the
calendar plist do not prove an actual machine sleep transition happened.
