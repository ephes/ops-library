# Redis package/service trial — 2026-10-03

Base: `9b2dc08` (prior authorized-keys trial, preserved unchanged).
Result commit and Sol high independent review are recorded by the coordinator.
Implementation: GPT-6.1 Sol low. This is a fresh contrasting slice, not a fleet
migration. Read ops-library instructions, the earlier two ops-meta Pyinfra specs,
current ops-control workflow evidence and the complete Redis role/Molecule setup.

## Setup and operational contract

The unchanged `redis_install` role is representative of apt, public configuration,
change-triggered handlers and enabled/running systemd service management. The
previous role had no package manager or process lifecycle. Redis adds both while
remaining one self-contained leaf: no app checkout, database migration, TLS,
proxy, inventory translation or cross-host coordination.

Each engine gets a separate disposable Debian 12 ARM64 container, with Python
3.14 controller, Ansible core 2.20.0 and Pyinfra 3.6.1. Ansible target modules use
Debian `/usr/bin/python3` plus `python3-apt`; this is distinct from controller
Python. Real systemd boots as PID1. Local Docker 29.2.1 is backed by the macOS
Colima Linux VM. Every Docker command pins a validated local Unix socket and
strips remote builder/daemon overrides. Native Linux invocation is refused.
The privileged containers request private cgroup namespaces, ephemeral `/run`
and `/tmp`, no host namespaces, no published ports, and no host cgroup, home,
production inventory, device or Docker socket mounts. Docker's privileged guest
access is broader than an unprivileged sandbox; this result does not show a
production isolation or SSH privilege story.

Build acquisition occurs outside per-engine invocation timings. A file-based
Debian package repository is assembled in the image with downloaded Redis and
dependency archives. Redis is absent before each first convergence; the engines
actually install it with apt, while container execution uses `--network none`.
This proves local Debian package/service convergence, not remote repository
availability, signing/repository setup or package version upgrades. The official
Redis repository option and authenticated configuration are explicitly outside
the Pyinfra trial's supported subset. Redis binds `127.0.0.1` inside each container,
password authentication is disabled, and no SOPS/key/plaintext secret is involved.

The Pyinfra implementation uses native apt/file/systemd operations and executes
the existing optional validation shell. It reuses the unchanged Ansible Jinja
config template, avoiding a second representation of Redis config. Restart is
gated by the upload's callable `did_change`, evaluated after operation execution.
It does not reproduce Ansible template backup archives or the password-mismatch
repair logic (auth is out of scope). Those remain maintenance/integration costs,
not claimed parity.

## Results and failure semantics

The final assertion scope covers first package installation, enabled/active service and PING,
PID/config/package stability across no-op, stopped+disabled service repair,
config-change restart with runtime `CONFIG GET maxmemory`, content/owner/mode
drift repair, malformed-config restart failure/recovery, injected broken real
systemd `ExecStart` failure/recovery, and final no-op. Final configs, ownership,
modes, active/enabled state, runtime memory and installed package versions match.
The installed version was `5:7.0.15-1~deb12u10`. No fake `systemctl` or lifecycle
mock was used. A SET/GET fixture verifies in-memory state survives no-op; restart
durability is not claimed because RDB saves/AOF are disabled in the fixture.

The optional existing `redis_install_validate_config=true` feature failed even
for valid configuration in this environment: the short-lived validation instance
never produced the expected pidfile and emitted "Redis validation failed to start
test instance." Both paths reproduce this behavior and preserve the running
service PID/config on disk. The hypothesis is Redis's port-0/no-listener test
setup exits before creating a usable pidfile; the cleanup removes its logfile,
so this is an inference, not a diagnosed production bug. The accepted normal
comparison uses the documented default `validate_config=false`. This probe is
not evidence that invalid configuration is rejected before writing or restarting.

With validation disabled, malformed loglevel is written before restart; restart
fails and the service becomes unavailable. Correcting configuration restores a
healthy service. The broken-ExecStart injection verifies systemd's effective
ExecStart contains the nonexistent executable, then causes a real restart
failure; removing the override and resetting failed state permits recovery even
when the desired config file is already correct. There is no atomic rollback or
zero-downtime claim. Interrupted uploads and connection-loss cleanup are untested.

Exact elapsed times and raw CLI change counts are in `results.json`.

| Scenario | Ansible seconds / raw changes | Pyinfra seconds / raw successes |
| --- | --- | --- |
| first | 2.552 / 5 | 0.71 / 8 |
| noop | 1.777 / 0 | 0.236 / 2 |
| service_drift_repair | 2.004 / 1 | 0.43 / 3 |
| config_restart | 2.09 / 2 | 0.404 / 4 |
| drift_repair | 2.169 / 5 | 0.333 / 10 |
| invalid_config_recovery | 2.112 / 2 | 0.286 / 4 |
| restart_recovery | 1.952 / 1 | 0.305 / 3 |
 Pyinfra's
raw operation Success counts are not a managed-state idempotency metric: apt
update and PING execute even when package, directory/file ownership and modes,
configuration, runtime settings and Redis PID remain stable. Ansible's steady
state reports zero changed tasks. Apt metadata refresh is performed on every
invocation in both paths; package acquisition is common offline fixture setup.
After the setgid repair, the observed Pyinfra no-op count is two: apt update
and PING. Neither file nor directory metadata, package version nor service PID
changes. The earlier four-operation no-op included the two repeating directory
commands and was not accepted as full metadata parity. This difference matters for operator-facing logs and would need a deliberate
normalization policy before an ops-control/FastDeploy integration.

## Economics and next decision

Implementation started about 22:26 UTC. Initial package/service lifecycle assertions passed
about 22:32 UTC (roughly six minutes), before expanded directory-metadata checks,
evidence writing and independent review. Two setup attempts failed: missing target python3-apt/interpreter setup,
and optional Redis validation failing valid initial convergence. Roughly two
minutes were spent diagnosing/repairing fixture bootstrap and narrowing the
validation claim; the production role remained unchanged. Expanded directory checks then exposed a real parity defect: Debian's packaged
config/log directories inherited setgid, and Pyinfra `files.directory(mode="755")`
emitted `chmod 755`, preserving setgid on Linux. The observed modes were 2755,
while Ansible enforced 0755; these operations also repeated on every invocation.
Pinned Pyinfra's `ensure_mode_int` removes leading zeros, so requesting `00755`
through the native mode argument cannot fix it. A small callable stat-fact gate
now issues explicit `chmod 00755` for all three scoped managed directories. Injected setgid drift on all three directories is repaired. All
three data/log/config directories are checked for exact modes and pwd/grp owner
IDs, no-op stability and final cross-engine equality. Diagnosing this and rerunning
expanded checks took roughly three extra minutes, including one harness fix for
incorrectly assuming Debian redis uid equals gid. This manual metadata invariant
is a maintenance cost absent from the Ansible implementation. No custom systemd
framework was necessary. Reusing the prior safety design and existing Redis
config/validation code reduces marginal effort; this is not an independent
from-scratch cost benchmark. Model tokens/billing and human active engineering
time are unavailable; measured agent elapsed is the only engineering cost proxy.

Final expanded integration passed about 22:39 UTC; implementation/docs/fixture
repairs took about 13 minutes total agent wall time, excluding independent review.
The accepted warm image build took 0.074 seconds. Initial cold acquisition
was part of implementation elapsed but not separately retained as a reliable
timer. Per-engine measurements exclude Docker startup and fixture assertions.

Single local sequential runs, shared package/image caches, Ansible-first order
and tiny fixture workloads do not support a fleet speed or cost forecast. The
floating Debian base/transitive dependencies also limit strict reproducibility.

**No-go for expanding Pyinfra into supported package/service roles on this
evidence; narrow go for further disposable experiments only.** The new evidence covers actual package and service state that
the earlier public-file slice could not establish, at low marginal model effort.
It also surfaces CLI change-accounting friction, narrower option support, missing
backup semantics, extra setgid repair logic and a real optional validation problem
shared with the current role. Runtime advantages alone do not repay ownership of two deployment systems.

Remaining costs: diagnose/fix Redis validation separately in a production-owner
worktree; decide whether honest raw-operation logs suffice; cost backup/auth and
SOPS/stdin transport parity if needed; exercise real package upgrade/rollback and
SSH/privilege interruption in a separate disposable target; and measure review
repair effort across additional role classes before any migration proposal.
No fleet inventory, FastDeploy change or live rollout follows from this trial.

Checks: five safety regressions passed in normal and simulated deeply nested fresh
checkouts with no initial tmp directory. Python compilation, Black23.12.1,
Ruff0.1.9 and diff checks passed; final Docker integration completion is recorded
with the result artifact.

## Final independent review and slice cost

The installed `codex-review-loop` proved `gpt-6.1-sol` at high effort and returned
CLEAN on the first review: zero findings, no skipped files, truncations or
redactions. Review runtime was 221.062 seconds (3m41s). No review-driven repair
was needed. The roughly thirteen-minute implementation interval includes the
bootstrap and setgid repairs described above; review time is additional.
Overall this second slice took approximately eighteen minutes from 22:26 to
22:44 UTC before commit/report. The prior slice's evidence and cost accounting
remain unchanged: approximately eighteen minutes there, including 339.270
seconds review and approximately three minutes review repairs. Together these
are two small local experiments, approximately thirty-six minutes task wall
time, not a model-billing or fleet-maintenance estimate.

Final checks: the expanded real Docker comparison passed with all three
managed-directory modes and injected setgid drift asserted; five safety tests
passed in ordinary/deep fresh checkouts; Black 23.12.1, Ruff 0.1.9, compilation
and `git diff --check` passed. The supported collection roles are untouched,
and the full collection suite was not rerun for this opt-in experiment. The
separate result commit is reported in the Herdr handoff on
`workspace/pyinfra-trial`. No merge, push or deployment follows from this work.
