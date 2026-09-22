# daybook_operations_runtime_deploy

Stage one API-backed scheduler in an existing protected macOS importer profile.

This role preserves the existing Full Disk Access interpreter path. It does not
install/update the importer checkout, initialize a ledger, change an activation
marker, or manage the long/native-work labels. Install the exact reviewed Daybook
revision using the existing importer maintenance procedure first; the role
verifies that revision and imports the new runtime with the protected interpreter.
Any source upgrade and its long-lane maintenance window must be reviewed separately.

`action: install` creates root-owned disabled policy, owner-private credential and
journal, and a candidate plist **outside** LaunchAgents. It never changes the
existing scheduler. A root-owned local policy only selects the fixed importer
adapter, binding and API origin. No server-supplied executable or path is accepted.

`action: cutover`, with `confirmed: true`, disables only the regular label,
waits for its current job to finish, unloads it, proves both importer/runtime locks
idle, saves the old plist once, and installs the new command. The journal/ledger
remain intact. Default `start: false` leaves it disabled. `start: true` additionally
requires reconciled journal/API state and an enabled server binding before loading.

`action: rollback` requires the server binding already disabled and no unresolved
assigned/awaiting-application work. It quiesces the same regular label, restores
the saved plist and disables the local policy. Optional `start: true` loads the
legacy command only after the remote active slot has been reconciled. This does
not restore an old ledger or delete API evidence. Failures leave the label disabled.

Example, installation only:

```yaml
- role: local.ops_library.daybook_operations_runtime_deploy
  vars:
    daybook_operations_runtime_user: example
    daybook_operations_runtime_revision: "{{ reviewed_daybook_commit }}"
    daybook_operations_runtime_token: "{{ private_profile_token }}"
    daybook_operations_runtime_api_url: https://operations.example.com
```

The user must have a GUI login for attended label changes. The role uses a
noninteractive login-style sudo user switch (`-H -S -n -i`), which enters the user's
home before Ansible starts its Python module. A root SSH session's working
directory may be inaccessible to that user on macOS. The login shell also loads
the user's shell configuration; recheck deployment after changing it. Commands
still use the absolute protected Python path with isolated mode. Configure credentials
with mode 0600 and the delivery directory with mode 0700. `operations status`
uses the same policy and exposes aggregate state only. After a crash, never clear
the journal: drain its receipt or authorize a linked recovery on the server,
then use `operations recover` locally. Runtime lock inheritance protects orphaned
children. No PID read from disk is killed by recovery.

## Defaults and variables

```yaml
---
ops_library_documentation_category: deployment
daybook_operations_runtime_action: install
daybook_operations_runtime_confirmed: false
daybook_operations_runtime_start: false
daybook_operations_runtime_user: CHANGEME
daybook_operations_runtime_home: "/Users/{{ daybook_operations_runtime_user }}"
daybook_operations_runtime_install_root: /Library/Application Support/Daybook/voice-memo-inbox
daybook_operations_runtime_python: "{{ daybook_operations_runtime_install_root }}/daybook/.venv/bin/python"
daybook_operations_runtime_revision: CHANGEME
daybook_operations_runtime_policy: "{{ daybook_operations_runtime_install_root }}/operations.json"
daybook_operations_runtime_importer_policy: "{{ daybook_operations_runtime_install_root }}/policy.json"
daybook_operations_runtime_credential: "{{ daybook_operations_runtime_home }}/.config/daybook-voice-memo-inbox/operations.json"
daybook_operations_runtime_token: CHANGEME
daybook_operations_runtime_api_url: https://operations.home.example.com
daybook_operations_runtime_binding: regular
daybook_operations_runtime_journal: "{{ daybook_operations_runtime_home }}/.local/state/daybook/operations-importer"
daybook_operations_runtime_mode: tick
daybook_operations_runtime_bindings: []
daybook_operations_runtime_adapters:
  - voice_memos.ingest.v1
  - voice_memos.transcribe_long.v1
daybook_operations_runtime_label: de.wersdoerfer.daybook.voice-memo-inbox
daybook_operations_runtime_plist: "{{ daybook_operations_runtime_home }}/Library/LaunchAgents/{{ daybook_operations_runtime_label }}.plist"
daybook_operations_runtime_staged_plist: "{{ daybook_operations_runtime_install_root }}/operations.launchd.plist"
daybook_operations_runtime_legacy_plist: "{{ daybook_operations_runtime_install_root }}/regular-importer.before-operations.plist"
```

## One binding or several

The defaults render the profile this service has always had: schema 1, one
binding, woken by launchd every 300 seconds through `operations tick`.

Setting `daybook_operations_runtime_bindings` to a non-empty list renders schema 2
instead, where every entry states its own `name`, `adapter`, `journal`, `cadence`,
`deadline` and `lease`. The list and `daybook_operations_runtime_mode: serve` go
together, and the role requires both or neither: `operations tick` with no
`--binding` cannot choose between several bindings -- it stops with
`ambiguous_binding` -- and launchd's single fixed wake-up could not honour their
separate cadences even if it could choose. A `serve` label with no list would
supervise the schema 1 binding by accident rather than by decision.

In `serve` the label runs the supervisor -- one long-lived process, one worker per
binding -- under `KeepAlive` rather than `StartInterval`, because the supervisor
owns its own due times and must not also be woken.

`KeepAlive` is only safe here because a binding that stops for an operator records
that stop beside its journal. The restarted supervisor reads the marker, reports
the reason and dispatches nothing; without it, the key would be a retry loop back
into the state a person was meant to look at first.

```yaml
daybook_operations_runtime_mode: serve
daybook_operations_runtime_bindings:
  - name: regular
    adapter: voice_memos.ingest.v1
    journal: /Users/SERVICE/.local/state/daybook/operations-importer
    cadence: 300
    deadline: 330
    lease: 600
  - name: long
    adapter: voice_memos.transcribe_long.v1
    journal: /Users/SERVICE/.local/state/daybook/operations-long
    cadence: 600
    deadline: 1200
    lease: 1500
```

The long lane's `deadline` is not a free choice. The client derives a minimum from
the importer policy the child will run under and refuses the whole profile when
the configured value is below it -- too small a deadline would kill a
transcription that was going to succeed. Under Studio's documented policy that
minimum is 1132 seconds; see the budget table in Daybook's `docs/operations.md`
before changing either the importer policy or this number. `lease` must exceed
`deadline` by at least 60 seconds, the time it takes to stop a child and deliver
its receipt.

`cadence`, `deadline` and `lease` must be whole numbers, not strings or floats
that happen to convert. The profile is written out exactly as given and the client
requires real integers, so a quoted `"300"` would pass a coercing check here and
then stop the entire profile when the client loads it.

Preserve the regular binding's existing journal path when moving to schema 2.
Create only the new long journal; do not copy, reinterpret or clear outstanding
deliveries during the upgrade. The role enforces this: the binding it is
transitioning must already exist in the previous profile with the same journal,
and a binding present there may be added to but never dropped, since a dropped
one leaves its journal holding an undelivered receipt nobody reads again.

The transition guards read either schema. They ask the client for status by
binding name rather than relying on an implied single binding, which a
multi-binding profile does not have.

`install` refuses to run over an enabled profile and `cutover` refuses to replace
one, by design: only `rollback` may act on an enabled runtime. Moving an already
enabled single-binding profile to a multi-binding one is therefore a full cycle --
disable the server binding, `rollback`, `install` the new profile staged, re-enable
the server binding, then `cutover`.

## Validation

Local contract tests exercise disabled defaults, rendered units/plists and lifecycle
safety. The Daybook suite exercises real PostgreSQL concurrency and dump/restore,
HTTP delivery recovery and importer regression fixtures. Live deployment and
attended import/rollback validation remain required before production acceptance.

## Offline incident rollback

Automated rollback requires central status. If the API is unavailable, fence both
central units independently (stopped and disabled, or server held offline), disable
and drain the regular local label, and use the supported `operations idle` CLI to
prove both local locks free without HTTP. Preserve/inspect journal and source
evidence before manually restoring the saved legacy plist and disabled policy.
Reconcile and disable the central binding before unfencing the server. The private
control runbook contains the attended steps; this is never an automatic bypass.
