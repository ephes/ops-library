# daybook_operations_runtime_deploy

Stage the Daybook operations supervisor on a client machine: one long-lived
process that asks the coordination server what to do and runs what it is handed.
On Studio it lives in the existing protected macOS importer profile; on a machine
deployed without root, such as Atlas, it is a user-owned install of its own (see
[Two kinds of machine](#two-kinds-of-machine-owner-and-mode)).

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
absence. The label must answer 113. Every journal or store the old profile names
must exist. A per-source journal of a schema 1 or 2 profile must have no halt marker,
and a slot that exists must read exactly `idle`. Only a journal with neither slot
nor `runtime.lock` counts as never opened; a lock without a slot is a used journal
whose evidence is gone, and is refused. A store (schema 3 or 4) must
have both its subdirectories and hold no delivery record or halt at all. Then it
writes the new profile **disabled** and a staged plist, and starts nothing; the
`cutover` that follows does the enabling, under its own guards. It never reads
the server, never touches the server binding, and never deletes an old journal --
those are left in place, drained, for a person to remove once satisfied.

`action: rollback` requires the server binding already disabled, no unresolved
assigned/awaiting-application work, and a store holding **no delivery record and
no stop marker for any source**, checked once the label is proven gone: the store
is shared by all of them, and the legacy importer a rollback restores reads
neither. It quiesces the same regular label, restores
the saved plist and disables the local policy.

`cutover` and `rollback` never stop a running supervisor. Disabling a KeepAlive
label does not stop it, and stopping it here could have launchd kill a long child
at its exit timeout. With the supervisor's label loaded -- running or between
runs, since KeepAlive would start it again -- they refuse at once and say so:
quiesce it by hand first, as the ops-control runbook describes (no active
operation, empty store, every source at least 90 seconds from due, then
`launchctl bootout`). A legacy importer run still in progress is waited for, as
before. Optional `start: true` loads the
legacy command only after the remote active slot has been reconciled. This does
not restore an old ledger or delete API evidence. Failures after the label has been
disabled leave it disabled; the refusal over a loaded supervisor comes before the
label is touched, and leaves it enabled and running as it was.

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

## Two kinds of machine: owner and mode

| Variable | Values | Meaning |
|----------|--------|---------|
| `daybook_operations_runtime_owner` | `root` (default), `user` | `root`: install, profile, staged and installed plist are root-owned (Studio). `user`: all of it belongs to `daybook_operations_runtime_user`, for a machine where deployment has no root (Atlas: `ansible_user` is the GUI user and `sudo` needs a password). The LaunchAgent passes `--policy-owner user`, the only way the client accepts a user-owned profile; the profile cannot vouch for itself. |
| `daybook_operations_runtime_mode` | `serve` (default), `host` | `serve`: the label runs the supervisor itself. `host`: the label runs the keeper, `operations host-keep`, which creates the machine's capability host if it is missing (with `work host ensure`'s lock and marker), starts the supervisor inside it as its own tmux session, and exits when either is gone so launchd starts it again. The supervisor's tasks then inherit the host's grants: a machine has one place that holds special permissions, and nothing is granted to a process of its own. `KeepAlive`, a 30-second throttle, and `LimitLoadToSessionType: Aqua`. |
| `daybook_operations_runtime_host_*` | socket `daybook-host`, session `host`, tmux, `TMUX_TMPDIR` `/private/tmp`, lock, application `Ghostty` | The capability host, in `host` mode. |
| `daybook_operations_runtime_code_bundle_src` | `""` (default), a path | A git bundle carrying the pinned revision, for a machine where no other role installs the code. The role then clones it into `install_root/daybook`, checks out exactly `daybook_operations_runtime_revision` detached, refuses a checkout that differs, and runs `uv sync --frozen --no-dev`. Empty: the code is already installed (Studio's importer role does that). |

**Stopping a hosted supervisor.** Booting out the keeper leaves the supervisor
running inside the host, by design. `cutover` and `rollback` therefore refuse
while the label is loaded running `serve` or `host-keep`, **and** while any
`operations serve` process of the user runs (`pgrep -f "[o]perations serve"`):
boot out the keeper, send SIGTERM to the supervisor so owned work finishes and
persists its receipt, wait for it to exit, then transition.

**A machine whose label never ran anything** (Atlas: its old jobs were other
labels, retired by their own roles). `cutover` saves no original command, because
there is none; `rollback` then leaves the label with no command at all, and
`start: true` bootstraps nothing -- the old jobs come back through their own roles.

**The profile is proven loadable at deployment.** After writing it, the role loads
it with the installed client, `Config.load(policy, owner)`, as the user. Every rule
the client applies -- each adapter's settings, whether a kind said it is long
where it must, the importer policy's budget, the owner -- fails the deployment
instead of the supervisor's start.

## Defaults and variables

```yaml
---
ops_library_documentation_category: deployment
daybook_operations_runtime_action: install
daybook_operations_runtime_confirmed: false
daybook_operations_runtime_start: false
daybook_operations_runtime_user: CHANGEME
# Who owns the install. `root`: a root-owned install, profile and LaunchAgent, as
# on Studio. `user`: a machine deployed without root, such as Atlas -- code,
# profile, credential and LaunchAgent belong to the GUI user, and the client is
# told so with `--policy-owner user` in the job's own arguments.
daybook_operations_runtime_owner: root
daybook_operations_runtime_file_owner: "{{ 'root' if daybook_operations_runtime_owner == 'root' else daybook_operations_runtime_user }}"
daybook_operations_runtime_file_group: "{{ 'wheel' if daybook_operations_runtime_owner == 'root' else 'staff' }}"
daybook_operations_runtime_home: "/Users/{{ daybook_operations_runtime_user }}"
daybook_operations_runtime_install_root: /Library/Application Support/Daybook/voice-memo-inbox
daybook_operations_runtime_python: "{{ daybook_operations_runtime_install_root }}/daybook/.venv/bin/python"
daybook_operations_runtime_revision: CHANGEME
daybook_operations_runtime_policy: "{{ daybook_operations_runtime_install_root }}/operations.json"
daybook_operations_runtime_importer_policy: "{{ daybook_operations_runtime_install_root }}/policy.json"
daybook_operations_runtime_credential: "{{ daybook_operations_runtime_home }}/.config/daybook-voice-memo-inbox/operations.json"
daybook_operations_runtime_token: CHANGEME
daybook_operations_runtime_api_url: https://operations.home.example.com
# The source the transition guards ask about (`operations status --binding`). A
# name the server knows; the machine holds no list of them.
daybook_operations_runtime_binding: regular
# The machine's one delivery store. A record in it belongs to an operation, not to
# a source, which is what lets a pool of workers hold several at once without one
# completion overwriting another's evidence. It is a new directory on purpose: the
# per-source journals of profile schemas 1 and 2 are left where they are, drained
# and untouched, rather than reinterpreted.
daybook_operations_runtime_journal: "{{ daybook_operations_runtime_home }}/.local/state/daybook/operations"
# 'serve' runs the supervisor as a plain LaunchAgent: one long-lived process with a
# pool of workers that take whatever the server hands out. 'host' runs the keeper
# (`operations host-keep`) instead, which keeps that supervisor alive inside the
# machine's capability host -- the one place on the machine that holds special
# permissions -- so every task it starts inherits the host's grants. 'tick' is
# gone: it needed a profile naming exactly one source, and a profile names none.
daybook_operations_runtime_mode: serve
# The capability host, for mode 'host': the Ghostty-born tmux server `work host
# ensure` creates, under its lock and marker.
daybook_operations_runtime_host_socket: daybook-host
daybook_operations_runtime_host_session: host
daybook_operations_runtime_host_tmux: /opt/homebrew/bin/tmux
daybook_operations_runtime_host_tmpdir: /private/tmp
daybook_operations_runtime_host_lock: "{{ daybook_operations_runtime_home }}/.local/state/daybook/host/host.lock"
daybook_operations_runtime_host_application: Ghostty
# A pinned source bundle to install the code from, for a machine where no other
# role installs it (Atlas). Empty: the code is already installed at the pinned
# revision -- on Studio the Voice Memo importer role does that.
daybook_operations_runtime_code_bundle_src: ""
daybook_operations_runtime_uv_bin: /opt/homebrew/bin/uv
daybook_operations_runtime_python_version: "3.14"
# The pool. `long` is how many workers long work may occupy at once, and it must
# leave at least one it cannot take: that is the guarantee the separate long
# thread used to give, now as a number. The client refuses a profile that breaks it.
daybook_operations_runtime_workers:
  count: 2
  long: 1
# The kinds of work this machine can run, and what running each costs here. Not
# sources: since step 3 of Daybook's central scheduling design the source list is
# the server's, a source is added with an insert there, and nothing here names one.
# The machine offers these kinds when it asks what to do. The long kind's deadline
# is not a free choice -- the client derives the minimum from the importer policy
# and refuses a profile that configures less. See the budget table in daybook's
# docs/operations.md.
daybook_operations_runtime_kinds:
  - adapter: voice_memos.ingest.v1
    deadline: 330
    lease: 600
daybook_operations_runtime_adapters:
  - voice_memos.ingest.v1
  - voice_memos.transcribe_long.v1
  - mail.work.v1
  - sessions.ship.v1
  - archive.classify_quotes.v1
  - weeknotes.reconcile.v1
  - voice_memos.work.v1
# The kinds that run the memo importer. Each gets `run.importer_policy` from
# `daybook_operations_runtime_importer_policy` unless it names its own `run`; a
# machine with none of them names no importer policy at all (profile schema 5).
daybook_operations_runtime_importer_adapters:
  - voice_memos.ingest.v1
  - voice_memos.transcribe_long.v1
daybook_operations_runtime_label: de.wersdoerfer.daybook.voice-memo-inbox
daybook_operations_runtime_plist: "{{ daybook_operations_runtime_home }}/Library/LaunchAgents/{{ daybook_operations_runtime_label }}.plist"
daybook_operations_runtime_staged_plist: "{{ daybook_operations_runtime_install_root }}/operations.launchd.plist"
daybook_operations_runtime_legacy_plist: "{{ daybook_operations_runtime_install_root }}/regular-importer.before-operations.plist"
```

## The profile: identity, kinds of work, a pool, and one store

The role renders profile schema 5 (the client reads 4 and 5; a schema 4 profile
upgrades in place, since the store does not change):

```yaml
daybook_operations_runtime_mode: serve
daybook_operations_runtime_journal: /Users/SERVICE/.local/state/daybook/operations
daybook_operations_runtime_workers:
  count: 2
  long: 1
daybook_operations_runtime_kinds:
  - adapter: voice_memos.ingest.v1
    deadline: 330
    lease: 600
  - adapter: voice_memos.transcribe_long.v1
    deadline: 1200
    lease: 1500
```

**Each kind may carry `long` and `run`.** `long` says whether the kind draws on
the long allowance; an adapter that fixes the answer (the long memo lane is always
long) cannot be overridden, and the publishing adapters require the profile to
say. `run` is the adapter's local settings -- paths and names its fixed command
needs on this machine -- checked per adapter by the client and never sent to the
server. The memo kinds get `run: {importer_policy: …}` from
`daybook_operations_runtime_importer_policy` unless they name their own; a machine
with no memo kind names no importer policy at all.

```yaml
daybook_operations_runtime_kinds:
  - adapter: mail.work.v1
    deadline: 120
    lease: 300
    run:
      state: /Users/SERVICE/.local/share/daybook/mail-work/work.sqlite3
      mail_state: /Users/SERVICE/.local/share/daybook/mail-work/mail.sqlite3
      # … the remaining mail settings, see Daybook's docs/operations.md
      search_path: [/opt/homebrew/bin, /usr/bin, /bin]
```

**No source.** Since step 3 of Daybook's central scheduling design the source
list is the server's: a source is a row there, added with an insert and changed
with an update, and the machine learns a source's name only from the answer to
its own question. The profile names what the machine *can run* -- each kind of
work with the child `deadline` and `lease` it needs on this hardware -- and the
machine offers those kinds when it asks what to do. How a kind is executed stays
fixed on the machine; the server never sends a command.

**One store** holds one delivery record per operation in flight (`deliveries/`)
and the stop markers (`halts/`, per source, plus `_store` for a record too corrupt
to attribute).

**A pool**, not a worker per source. `serve` runs one supervisor whose
`workers.count` threads take whatever is ready. Long work may occupy at most
`workers.long` of them, and the role and the client both refuse a value that does
not leave at least one worker it cannot take; once the allowance is spent, the
machine stops offering long work, so the server cannot hand any out.

The label runs under `KeepAlive` rather than `StartInterval`, because the server
owns the due times and the process must not also be woken. That is only safe
because a stopped source records its stop in `halts/`; a restarted supervisor
reads it, withholds that source from every question, and dispatches nothing for it.

The long kind's `deadline` is not a free choice. The client derives a minimum from
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

Kinds of work may be added and never silently dropped, and once there is a store
it may not move: either would strand records nobody could finish. Changing the
profile's *shape* -- from the per-source journals of schemas 1 and 2, or a schema
3 profile that still named sources -- is what `replace` is for, and only
`replace`: `install` over a disabled old profile would skip the check that the
label is quiesced.

`install` refuses to run over an enabled profile and `cutover` refuses to replace
one, by design: only `rollback` may act on an enabled runtime, and only `replace`
may change the profile's shape.

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
