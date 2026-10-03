# Redis candidate-install transaction — 2026-10-03

Isolated branch: `workspace/redis-transactional-config`.
Base: `96bfa783456ecf91ba2327e85bac9fc48d87ec67`.
Historical `EVIDENCE.md` and `results.json` are unchanged. This is a separate,
bounded follow-up to the optional-validator repair, not a production deployment.

## Reproduction before repair

The existing real Redis/systemd fixture was strengthened to require that invalid
configuration preserve the prior disk file. Before role changes:

```text
uv run python tests/redis_validation/run.py
AssertionError: Invalid candidate replaced active disk configuration
```

The fixture had already verified the prior running PID and PING survived.
This proves the missing boundary was the active on-disk configuration, not the
previous no-listener bug or a mocked Redis startup.

## Design and implementation

Ansible's installed core2.20 `copy` implementation validates only changed file
content, creates a backup before `validate`, and unlinks a symlink destination
before validation. Metadata-only repair can report changed without invoking
native validation. These concrete source observations ruled out using the
native template `validate` hook alone for the required boundary.

With validation enabled, the role instead creates a private mode-0700 directory,
renders a root-owned mode-0600 candidate and mode-0700 validator script, validates
the candidate, then uses Ansible's atomic remote copy to install it. Backup and
restart notification occur only at this accepted installation step. Every
candidate is validated, including unchanged content and metadata-only repair;
a no-op preserves the service PID and reports zero changes. Ephemeral rendering
is hidden from diff output. An `always` block removes the candidate/script
subdirectory on normal success/failure; validator EXIT/INT/TERM traps remove its
private Redis process/socket/log artifacts. The validation parent may remain empty.

Disabled validation retains direct-template behavior. Check mode predicts the
configuration change without creating the candidate/script or starting Redis.
The collection patch version is 2.25.2. No generalized deployment transaction,
new runtime dependency, service-restart rollback or remote deployment was added.

## Real disposable proof

The existing safety-guarded runner was reused. Only the new role template was
added to its source allowlist; transport, build-environment, symlink and mount
safeguards are unchanged. macOS Colima's local Unix Docker socket ran a
network-disabled disposable privileged Debian12 ARM64 container with real
systemd PID1. Ansible core2.20 on Python3.14 controlled the target's Debian
Python3.11/apt; Redis `5:7.0.15-1~deb12u10` was installed by the role from the
image-local offline repository. There were no production inventories, real
secrets, SSH connections, published ports or host-system mounts.

Final measurements are in `transactional-results.json`. The warm image build
took 0.076 seconds. Actual role deployments prove:

- Baseline direct installation and successful optional validation.
- Accepted 32 MiB change restarts the service and changes the runtime value.
- Rejected syntax preserves active file bytes, inode, mtime, mode, owner/group,
  existing backup set/content, running PID and PING. The invalid directive is
  absent from Ansible output. A valid retry reports zero changes and no restart.
- Controlled TERM interruption for a changed candidate and for metadata-only
  repair: a pass-through guest wrapper launches the actual Redis binary and
  pauses its return. The fixture checks the real process executable, private
  socket, root ownership and candidate/script/directory permissions, then signals
  the actual validator shell. Validator rc143 makes deployment fail; the prior
  file/metadata/backups/PID/PING survive and all private validator artifacts and
  processes are removed. The wrapper exists only in the disposable guest and is
  removed after each case; it does not substitute a fake Redis implementation.
- Successful metadata repair restores root:root mode0644 after validation.
- Corrected 48 MiB recovery restarts Redis and changes the runtime value.
- A subsequent validated no-op preserves PID and reports zero changes.
- Check mode predicts the 64 MiB change without altering disk, backups, service
  PID or creating validator artifacts.

## Checks and existing failures

- `uv sync --frozen`: passed in this isolated worktree's own virtualenv.
- `uv run python -m unittest discover -s tests/redis_validation -p 'test_*.py'`:
  five safety regressions passed.
- `just test-role redis_install`: YAML, structure, defaults and templates passed.
- `uv run ansible-lint roles/redis_install/tasks/configure.yml`: passed.
- Role-wide `uv run ansible-lint roles/redis_install`: fails on sixteen existing
  task-name prefix violations in unchanged install/service/validate task files.
  New/touched configuration task names now use the required prefix.
- Changed-file pre-commit checks passed for role/docs/fixtures/version files after
  Black reformatted the fixture. The changed `CHANGELOG.md` still fails the
  existing duplicate historical Security/Fixed/Changed heading rule at lines
  306/320/357; those older headings were not changed in this slice. No hook was
  disabled or global configuration changed.
- Rendered validator `bash -n`, fixture Python compilation, Jinja syntax, secret
  scanning and diff checks passed. Shellcheck is not installed globally and its
  pre-commit hook does not select `.j2`; no shellcheck result is claimed.
- `just docs-build`: completed with five existing unresolved MyST references in
  unrelated Takahe/software-estate pages and TESTING.md's prior fixture link.
  The command is `sphinx-build -E -n` without `-W`, despite the testing guide's
  strict wording. `just docs-lint` passed with its existing relative-link warnings.
- The broad all-services/default contributor suite was not run: this slice used
  the authorized focused real Redis fixture and role/document checks, without
  unrelated service integration or heavy native builds. Existing unrelated jobs
  were inspected before the serialized Docker runs; warm builds used cache.

## Limits and handoff

The demonstrated transaction ends at accepted atomic configuration installation.
A later restart failure, interruption after acceptance/before promotion or the
restart handler, abrupt host loss, or loss of target connectivity is not a
service/config rollback guarantee. An unreachable target may prevent cleanup;
operators must inspect leftovers and rerun when connectivity returns. Filesystem
crash durability, unusual symlink destinations, concurrent role invocations,
other OS/Redis/Ansible versions, SOPS and authenticated configurations were not
tested. Validation remains opt-in. Only synthetic guest data was used.

The coordinator owns the independent Sol high review and local commit. No commit,
merge, push or deployment was performed by the implementation lane.

## Independent-review cleanup repair

The required Sol high review identified one material Warning: INT/TERM traps
could call `exit` while the EXIT cleanup trap was polling a slow-terminating
validator. Bash does not rerun an EXIT trap interrupted this way, leaving the
process or artifact directory behind. The initial real integration only signaled
before cleanup and did not detect this boundary.

Repair began at **2026-10-02 23:54:27 UTC** (2026-10-03 local date). A new local
test runs the actual rendered script against a synthetic owned Redis stand-in
that ignores TERM until KILL. After the first termination signal proves EXIT
cleanup is polling, the test repeatedly signals the validator shell with TERM
and INT. Against the pre-repair script it failed in **0.531 seconds**, finding
its private artifact directory still present; the fixture forcibly removed its
own process afterward.

Cleanup now captures the original exit status and replaces INT/TERM exit traps
with deferred failure recording while polling/removing artifacts. It completes
termination and removal before exiting. An interrupted successful cleanup exits
nonzero; an existing failure status is retained. No candidate is promoted from
an interrupted validation. The new tests cover both initially successful and
initially rejected validation, repeated TERM/INT, process termination and artifact
removal. An independent extension also exposed process-group TERM interrupting
the polling sleep under `set -e`. Two owned-session group cases failed in
**0.701 seconds**, again asserting leftover artifacts before exit status. Polling
now tolerates interrupted sleeps and continues cleanup. Both shell-directed
and process-group signals are tested; group signals target only a fresh owned
validator session. They use checkout-owned temporary directories and relative socket binding
in the stand-in, so deep review paths and review filesystem constraints remain
supported. Early-failure teardown reads the owned pidfile even before the cleanup
marker is observed.

Post-repair checks:

- `uv run python -m unittest discover -s tests/redis_validation -p 'test_*.py'`:
  final nine tests passed in **21.159 seconds** (five safety and four cleanup
  regressions). The earlier shell-only iteration passed seven tests in 11.465
  seconds before the group extension was added.
- `uv run python tests/redis_validation/run.py`: real disposable integration
  passed every earlier configuration/service/permission/backup/no-op/check-mode
  invariant, including handled before-cleanup TERM exit status143. Warm image
  build **0.069 seconds**; exact scenario measurements are in
  `cleanup-repair-results.json`. Earlier transaction measurements remain intact.
- Rendered `bash -n`, Python compilation, focused configuration Ansible lint,
  `just test-role redis_install`, changed-file pre-commit checks and diff checks
  passed. `just docs-build` again completed with the same five existing reference
  warnings; `just docs-lint` passed with existing relative-link warnings.
- The original unrelated role-wide lint/changelog heading failures and bounded
  test/deployment limits above remain unchanged. No global configuration, other
  role, historical evidence or prior Cast lane was modified.

Implementation and final checks completed by **2026-10-03 00:02:27 UTC**,
**eight minutes** after the measured start, including the independently requested
process-group extension. Final evidence bookkeeping follows that measurement.
No billing, token-cost or human active-time estimate is claimed.
Independent repair review and commit remain the coordinator's responsibility.

## Second independent-review cleanup repair

Fresh required Sol high review of baseline
`db41ff2c94df72522e9adbc2e71368cfa177dcf1` identified the same material cleanup
boundary in additional operations: process-group TERM could interrupt external
`cat` or `rm`, triggering `set -e` and aborting cleanup despite the deferred shell
signal handler. A prior failure1 could become143, with artifacts left and, when
PID reading was interrupted, the validator process surviving.

The implementation lane's measured receipt/start was **2026-10-03 00:07:01 UTC**.
Owned paused-command regressions were added before this repair:

```text
uv run python -m unittest discover -s tests/redis_validation -p test_cleanup.py -k pid_read
FAILED: private artifact directory remained (0.709 seconds)
uv run python -m unittest discover -s tests/redis_validation -p test_cleanup.py -k during_removal
FAILED: private artifact directory remained (5.965 seconds)
```

Both asserted artifact removal before exit status, rather than treating143 alone
as the defect. The fixtures always terminated their own stand-in process on
failure. Signals target only the freshly created validator process group.

Cleanup now reads the PID with a shell builtin, eliminating external `cat` at
that boundary. The owned removal subprocess ignores INT/TERM before executing
`rm`; its invocation is guarded against `set -e` and retried at most three times.
Existing failure status is retained. Permanent removal failure emits only a
generic error and fails validation, without an infinite retry or successful
candidate promotion. Filesystem failure can still leave artifacts for inspection;
this is an explicitly failed cleanup, not a cleanup-success claim.

The paused `cat` regression now proves no cleanup `cat` subprocess is executed.
The paused `rm` regression proves signal protection is inherited by that owned
subprocess, removal completes, the stand-in is gone and original failure1 remains.
A further permanent-removal-failure case proves exactly three attempts, generic
failure diagnostics and nonzero status even when validation initially succeeded.
Its intentionally unremovable synthetic artifacts are removed by test teardown.

Final repair validation:

- Twelve safety/cleanup tests passed in **38.526 seconds**, covering all seven
  cleanup cases plus the five unchanged runner-safety cases.
- Real disposable Redis/systemd integration passed all eleven prior configuration,
  service, permission, backup, recovery, no-op, metadata and check-mode scenarios.
  Warm build **0.066 seconds**; measurements are in
  `cleanup-operations-results.json`. Earlier evidence/results remain intact.
- Focused configuration Ansible lint, rendered `bash -n`, Python compilation,
  `just test-role redis_install`, current changed-file pre-commit and diff checks
  passed. `just docs-build` completed with the same five existing reference
  warnings; `just docs-lint` passed with existing relative-link warnings.
- Candidate-install logic, original configuration/service invariants, version and
  runner isolation/safety guards are unchanged by this repair. No global change,
  commit or deployment was performed. The coordinator owns fresh repair review.

Implementation, tests, documentation and checks completed by
**2026-10-03 00:12:44 UTC**, **five minutes 43 seconds** after the measured
receipt/start. Final timing bookkeeping follows that measurement; billing, token
cost and human active engineering time remain unmeasured.

## Final independent gate and integration

The installed supervised `codex-review-loop` completed three OpenAI reviews,
with session records proving `gpt-6.1-sol` at **high** effort in every round:

| Round | Scope | Result | Measured duration |
| --- | --- | --- | --- |
| 1 | Full candidate-install slice | One material cleanup Warning | 171.510 s |
| 2 | First cleanup repair delta | One material command-interruption Warning | 148.675 s |
| 3 | Second cleanup repair delta | CLEAN, zero findings | 117.926 s |

Both accepted warnings were reproduced, repaired and closed by fresh scoped
review. No unresolved review findings remain. All runs had no skipped files,
truncations, redactions, exclusions or forbidden tool uses; their throwaway
copies were removed. The existing unrelated lint/document warnings listed above
remain outside this slice's clean review verdict. No Anthropic or substitute
provider/model was invoked.

The coordinator independently reran the real eleven-scenario Redis fixture,
the role checks and focused Ansible lint, and the final twelve local tests
(**39.596 seconds**). The original validator evidence files were verified
unchanged. Readiness elapsed **40 minutes 33 seconds**, measured from
2026-10-02 23:36:12 UTC to 2026-10-03 00:16:45 UTC. Review-driven implementation
and checks took **13 minutes 43 seconds** across the two repairs; supervised
reviews took **438.111 seconds** total. Final documentation/commit bookkeeping
follows readiness. Billing, account quota and raw token usage are not inferred
from these wall-clock measurements.

Integrate the independently mergeable `96bfa78` validator repair first, then this
branch's separate candidate-install commit. If the base is already integrated,
apply only the follow-up commit. Reconcile collection version 2.25.2 with other
pending release work before publication. Do not apply older trial branches or
change installed skills. No merge, push, collection installation or deployment
was performed here; the prior Cast commits remain closed and preserved.

Owner acceptance on the intended OS/Redis version and authenticated configuration
is still pending. Before an eventual authorized rollout, test the opt-in validator
in that environment and preserve a recoverable known-good config. Validation is
still disabled by default. The accepted-install/restart gap, permanent cleanup
failure and crash/concurrency/filesystem/version limits above remain explicit;
this slice does not establish a general transactional deployment guarantee.
