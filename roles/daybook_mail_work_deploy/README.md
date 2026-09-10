# daybook_mail_work_deploy

Schedules Daybook's mail worker on a Mac where a LaunchAgent cannot reach
anything it needs.

macOS attributes a process to its *responsible process*, and a launchd agent is
its own — so it gets neither Full Disk Access to Mail's `Envelope Index` nor
Automation to MoneyMoney and Receipts Space, and its Apple Events **hang** to
`-1712` rather than refusing. That attribution is inherited through the spawn
chain, though, including across a daemonised tmux server. So this role installs
two agents: one that keeps a *capability host* alive — a tmux server started
from Ghostty, which does hold those grants — and one that couriers the ordinary
`daybook work mail` command into it.

The role does not install Daybook, read mail, drive an application, or touch the
voice-memo scheduler.

## The two agents, and why they enable separately

| variable | label | what it runs |
|---|---|---|
| `daybook_mail_work_host_enabled` | `de.wersdoerfer.daybook.mail-work-host` | `daybook work host ensure` at login and hourly |
| `daybook_mail_work_worker_enabled` | `de.wersdoerfer.daybook.mail-work` | `daybook work mail --via-host` every `daybook_mail_work_interval_seconds` |

Two controls rather than one, because the rollout needs three states: both off,
host only, then both on. The role asserts that the worker cannot be enabled
without the host — without one, every run exits non-zero reporting
`capability_host_absent`. Each label is disabled, booted out and reloaded
independently; the work database, watermark and logs survive either being turned
off.

`host ensure` is the only way the host is started. It takes an exclusive lock,
refuses to adopt a tmux server it did not create, and reaches `open` only when
nothing answers. Wiring an agent straight at `open -na Ghostty` would skip the
lock and the provenance marker, and would leave a spare application instance
behind on every run.

## What a scheduled run does

1. Ask the host whether it is there. `has-session` on a missing socket refuses in
   **49 ms** — and unlike `new-session` it does not create a server that would
   have no capability anyway.
2. Inject `daybook work mail` into the host and wait for that attempt only.
3. Report the inner run's JSON and exit code.

Single-flight is **not** here. It lives on the watermark transaction inside
`work_mail`, because the injected command is plain `work mail` and a lock held by
the courier would not cover a run started any other way.

## Conditions this is expected to meet in normal use

Neither of these is a fault, and neither should be treated as one:

- **The Mac sleeps.** launchd fires a missed `StartInterval` once on wake rather
  than replaying every tick it slept through, which is the coalescing this worker
  wants: an outage becomes one wider window, never a backlog of runs. The tmux
  host survives sleep; it does not survive a reboot, which is what `RunAtLoad`
  plus the hourly ensure are for. A run that was in flight when the machine slept
  can surface afterwards as an overdue lease — see the runbook, and note that an
  overdue lease is only ever *reported*, never killed or replayed.
- **MoneyMoney locks its database.** Outside working hours `export accounts`
  answers `Locked database. (-2720)`. That is the application refusing, not TCC:
  a permission failure is `-1712` and takes 20 seconds, while `-2720` comes back
  at once. Mail still reads, the session still runs, and the bookkeeping half is
  recorded as unfinished work for a later session — which is the intended
  behaviour, not a failure to fix here. The watermark still advances, because a
  session was launched; the prose on the work record is what carries the rest.

## Where the state lives

`daybook_mail_work_state_path` and `daybook_mail_work_mail_state_path` are not
tied to the runtime directory. If the worker has already been run by hand on the
host, point them at those databases: manual and scheduled runs then share one
watermark and take the same lease, so they cannot process the same mail twice,
and the stored watermark means no seeding is needed at all. A separate, fresh
state would keep a second watermark over the same mailbox that no manual run
knows about. The runtime directory holds only the courier's attempts, lock and
logs.

`daybook_mail_work_notify_config_path` must already exist; the role checks it
rather than letting every notification fail later.

## Claude only

`daybook_mail_work_provider` must be `claude`. The inheritance measurement covers
`ClaudeNativeAdapter`, which spawns its per-work tmux server from inside the
host. `CodexNativeAdapter` may instead attach to an app-server started outside
that spawn chain, and nothing has measured whether such a process carries the
host's grants.

## `--since` is never deployed

An explicit window start overrides the stored watermark. A pinned one would make
every run begin at the same point and take a fresh end — a fresh source identity
each tick, over a history that only grows. The role asserts that no rendered
plist contains `--since`; seed the watermark once by hand, and use `--reseed` to
move it deliberately.

## What it does not protect against

The capability host is reachable by **every process running as the owner**,
including an SSH login, and it holds Ghostty's grants for as long as it lives.
Unix permissions cannot separate the scheduler from anything else under one UID.
This is an accepted trade-off, recorded in
`daybook/docs/specs/2026-09-10-mail-worker-capability-host.md`; deploy this role
only where that has been read and agreed.

## Variables

See `defaults/main.yml`. `daybook_mail_work_service_user`,
`daybook_mail_work_assignment_path` and `daybook_mail_work_cwd` are `CHANGEME`
and must be supplied. Paths are asserted against fixed owner-private locations
rather than trusted.
