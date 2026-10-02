# Redis validator investigation — 2026-10-03

Isolated branch: `workspace/redis-validation-fix`.
Base: `5b6c2dad34d35fe2f60307f17edea2a9d370ac4d`.
Result/ref and independent Sol high review are recorded by the coordinator.
All writes are confined to this isolated worktree; no production role deployment,
original checkout edits or Pyinfra trial modifications occurred.

## Diagnosis

This is an existing Ansible role defect rather than a systemd fixture artifact.
The role starts a validation instance with TCP port 0 but no Unix socket. A direct
foreground reproduction against the real installed Redis 7.0.15, retaining its
synthetic logfile, emitted **Configured to not listen anywhere, exiting.**, exited
without a pidfile and left the running production-equivalent fixture PID intact.
The role's daemonized variant therefore cannot produce its expected pidfile and
rejects otherwise valid configuration. This matches the authoritative Redis 7
[source no-listener check](https://raw.githubusercontent.com/redis/redis/7.0/src/server.c)
and [configuration semantics](https://raw.githubusercontent.com/redis/redis/7.0/redis.conf):
port 0 disables TCP; a Unix listener must be configured separately. No inference
from mocked lifecycle commands is involved.

## Repair and actual tests

The optional validator now creates a private mode-0700 mktemp subdirectory under
its configured root and listens only on a temporary Unix socket with mode0700.
Systemd supervision is disabled for this standalone disposable process. PID/socket
readiness and process existence are checked; an exit trap terminates the instance,
polls for termination with SIGKILL escalation if needed, and removes generated
artifacts. Raw Redis diagnostics
are directed into the private temporary logfile and removed, while Ansible gets
a generic failure message to avoid exposing config directives in logs.

The role still renders the desired config before validation. An invalid config
stops before handler flush and preserves the running service, but leaves the
invalid desired file on disk. This repair does not introduce transactional config
rollback or prove safe interrupted connections. README usage and troubleshooting
now accurately explain that boundary. Collection patch version: 2.25.1.

Real Ansible core2.20.0 on Python3.14 controller, Debian Python3.11/apt target,
Redis package `5:7.0.15-1~deb12u10`, Debian12 ARM64 and systemd PID1 were used.
A local macOS Colima Docker Linux VM ran a disposable privileged private-cgroup
container; the runner rejects SSH/TCP Docker endpoints and strips remote builder
overrides. No live host, port, secret/inventory, home or host cgroup mount is used.
Redis was absent before convergence, installed by the real role using its apt task
against a local offline Debian repository, and bound only to container localhost.

The fixed role passed valid validation without replacing the existing Redis PID;
valid maxmemory change with a real restart/runtime check; invalid syntax rejection
preserving prior PID/PING; corrected recovery with restart; zero-changed validated
no-op; and process/artifact cleanup after valid and invalid cases. A separate
assertion verifies the invalid config directive is absent from Ansible output.
Exact final measurements are in `results.json`. Five runner-safety regressions passed both normal and deep fresh-checkout
contexts with initially absent tmp directories.
Python compilation, Black23.12.1, Ruff0.1.9, rendered-shell `bash -n`, targeted role `ansible-playbook
--syntax-check`, and diff checks passed. Shellcheck was unavailable and not
installed globally. Other supported
Redis/OS versions, SOPS and authenticated configs were not tested in this slice.

## Engineering cost

Implementation GPT-6.1 Sol low started about22:46UTC. Direct diagnosis was observed
by about22:48UTC; first fixed-role integration passed about22:50UTC. A missing
fixture `pgrep` dependency required adding procps; no production logic change
was needed for that fixture repair. Existing safety-runner design was reused
read-only, but no Pyinfra runtime or trial artifacts are dependencies. Final
redaction/process-cleanup assertions, docs and format verification finished about
22:53UTC, approximately seven minutes total implementation agent wall time before
independent review. The accepted warm image build took 0.071 seconds;
engine invocations are recorded individually and exclude Docker startup, build
acquisition and assertions. Independent review repair effort is recorded by the
coordinator. Token attribution,
billing and human active engineering time are unavailable; no dollar savings
estimate is claimed.

No deployment follows this fix. The next production-owner decision is whether to
roll out this reviewed patch in their own workflow and separately evaluate
transactional configuration replacement if invalid on-disk config is unacceptable.

## Independent review repair

Sol high round 1 identified one stale published role page claiming the validator
used `--test-memory`. The bootstrap Redis page now describes the private Unix
socket, standalone supervision, process/artifact cleanup, disabled default and
invalid-config disk/running-process boundary. A search of Redis role/docs
references found no other stale hook method. This documentation-only repair took
about one minute; no code or regression fixture changed.
`python3 validate_docs.py` passed with its relative-link warnings; diff check
passed, and the corrected published page contains no `--test-memory` reference.

## Final review and handoff

The installed `codex-review-loop` proved GPT-6.1 Sol at high effort in both
rounds. First review found one accepted documentation warning, which was fixed;
scoped re-review returned CLEAN with no unresolved findings. Neither review
skipped, truncated or redacted files. Runtimes were 180.592 and 70.730 seconds:
251.322 seconds (4m11s) total. Initial implementation/checks took approximately
seven minutes, documentation repair approximately one further minute, and this
lane approximately fifteen minutes wall time from 22:46 to 23:01 UTC before
commit/report. Token/billing/human-labor costs remain unmeasured.

The local result commit is reported in the Herdr handoff for isolated branch
`workspace/redis-validation-fix`, based on the original role baseline. The prior
Pyinfra trial commits `9b2dc08` and `6981c4a` remain unchanged on
`workspace/pyinfra-trial`; their evidence/cost accounting is preserved. The
production-owner follow-up is to assess applying this patch through their own
reviewed deployment workflow. This lane performs no deploy, merge or push.
