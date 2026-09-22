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

`action: replace`, with `confirmed: true`, changes the shape of the delivery store
on a runtime whose regular label is already quiesced -- in practice, right after
the attended importer upgrade has booted it out. It exists because the installed
client reads only the current profile schema, so it cannot be asked about the old
one, and the ordinary `rollback`/`install` cycle asks it exactly that. `replace`
instead proves the old state by reading the files, and refuses to pass on their
absence. The label must answer 113. Every journal the old profile names must
exist. A per-source journal of a schema 1 or 2 profile must have no halt marker,
and a slot that exists must read exactly `idle`. Only a journal with neither slot
nor `runtime.lock` counts as never opened; a lock without a slot is a used journal
whose evidence is gone, and is refused. A schema 3 store must
have both its subdirectories and hold no delivery record or halt at all. Then it
writes the new profile **disabled** and a staged plist, and starts nothing; the
`cutover` that follows does the enabling, under its own guards. It never reads
the server, never touches the server binding, and never deletes an old journal --
those are left in place, drained, for a person to remove once satisfied.

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
# The machine's one delivery store. A record in it belongs to an operation, not to
# a source, which is what lets a pool of workers hold several at once without one
# completion overwriting another's evidence. It is a new directory on purpose: the
# per-source journals of profile schemas 1 and 2 are left where they are, drained
# and untouched, rather than reinterpreted.
daybook_operations_runtime_journal: "{{ daybook_operations_runtime_home }}/.local/state/daybook/operations"
# 'serve' runs the supervisor: one long-lived process with a pool of workers that
# take whatever the server hands out. 'tick' is one launchd wake-up per check and
# only makes sense for a profile with exactly one source.
daybook_operations_runtime_mode: serve
# The pool. `long` is how many workers long work may occupy at once, and it must
# leave at least one it cannot take: that is the guarantee the separate long
# thread used to give, now as a number. The client refuses a profile that breaks it.
daybook_operations_runtime_workers:
  count: 2
  long: 1
# The sources this machine can run, and what running each costs here. No journal
# and no cadence: the journal is the machine's, and the server has answered when a
# check is due since step 1 of Daybook's central scheduling design. The long lane's
# deadline is not a free choice -- the client derives the minimum from the
# importer policy and refuses a profile that configures less. See the budget
# table in daybook's docs/operations.md.
daybook_operations_runtime_bindings:
  - name: regular
    adapter: voice_memos.ingest.v1
    deadline: 330
    lease: 600
daybook_operations_runtime_adapters:
  - voice_memos.ingest.v1
  - voice_memos.transcribe_long.v1
daybook_operations_runtime_label: de.wersdoerfer.daybook.voice-memo-inbox
daybook_operations_runtime_plist: "{{ daybook_operations_runtime_home }}/Library/LaunchAgents/{{ daybook_operations_runtime_label }}.plist"
daybook_operations_runtime_staged_plist: "{{ daybook_operations_runtime_install_root }}/operations.launchd.plist"
daybook_operations_runtime_legacy_plist: "{{ daybook_operations_runtime_install_root }}/regular-importer.before-operations.plist"
```

## The profile: sources, a pool, and one store

The role renders profile schema 3, which the Daybook client requires:

```yaml
daybook_operations_runtime_mode: serve
daybook_operations_runtime_journal: /Users/SERVICE/.local/state/daybook/operations
daybook_operations_runtime_workers:
  count: 2
  long: 1
daybook_operations_runtime_bindings:
  - name: regular
    adapter: voice_memos.ingest.v1
    deadline: 330
    lease: 600
  - name: long
    adapter: voice_memos.transcribe_long.v1
    deadline: 1200
    lease: 1500
```

**No journal and no cadence per source.** A delivery record belongs to an
operation, not to a source, so the store is the machine's and holds one record per
operation it is still answerable for -- `deliveries/` for those, `halts/` for the
per-source stop markers. The server has decided when a check is due since step 1
of Daybook's central scheduling design, so a cadence here would be a second copy
with no owner.

**A pool, not a worker per source.** `serve` runs one long-lived supervisor whose
`workers.count` threads take whatever the server hands out, so a source costs a
row rather than a thread and there is no cap on how many may be listed. The
requirement that a blocked long source must never stop ordinary discovery is kept
as a number: long work may occupy at most `workers.long` of them, and the role and
the client both refuse a value that does not leave at least one worker it cannot
take. `tick` remains for a profile with exactly one source.

The label runs under `KeepAlive` rather than `StartInterval`, because the server
owns the due times and the process must not also be woken. That is only safe
because a source that stops for an operator records the stop in `halts/`; a
restarted supervisor reads it and dispatches nothing for that source.

The long lane's `deadline` is not a free choice. The client derives a minimum from
the importer policy the child will run under and refuses the whole profile when
the configured value is below it -- too small a deadline would kill a
transcription that was going to succeed. Under Studio's documented policy that
minimum is 1132 seconds; see the budget table in Daybook's `docs/operations.md`
before changing either the importer policy or this number. `lease` must exceed
`deadline` by at least 60 seconds, the time it takes to stop a child and deliver
its receipt.

`deadline`, `lease` and both pool numbers must be whole numbers, not strings or
floats that happen to convert. The profile is written out exactly as given and
the client requires real integers.

Sources may be added and never silently dropped, and within schema 3 the store
may not move: either would strand records nobody reads again. Changing the store's
*shape* -- from the per-source journals of schemas 1 and 2 to this one -- is what
`replace` is for, and only `replace`: `install` over a disabled old profile would
skip the check that the label is quiesced.

`install` refuses to run over an enabled profile and `cutover` refuses to replace
one, by design: only `rollback` may act on an enabled runtime, and only `replace`
may change the store's shape.

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
