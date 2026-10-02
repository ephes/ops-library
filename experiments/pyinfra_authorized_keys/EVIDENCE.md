# Measured evidence — 2026-10-03

Base: `5b6c2dad34d35fe2f60307f17edea2a9d370ac4d`.
Result: trial files only; local result commit recorded by the coordinator.
Implementation model: GPT-6.1 Sol, low effort. Independent review and any
post-review repair effort are recorded separately by the coordinator.

## Setup and provenance

Read the applicable ops-library AGENTS/CLAUDE instructions and the two ops-meta
specs `2026-02-02_pyinfra_migration.md` and
`2026-03-12_pyinfra_sops_age_integration_spike_prd.md`. Read ops-control's current
AGENTS/CLAUDE, deployment/setup/tests/misc recipes without editing that repository
or reading production inventory or secret values. Current `deploy-one` still
uses service metadata and Ansible; `pyinfra-deploy-one` and the secret/inventory
support tests remain as a narrow reference path. The historical Archive 16/25
result informs this trial but does not decide it.

Docker 29.2.1 was available. Real Ansible local connection and Pyinfra `@local`
operations ran inside an isolated Debian 12 ARM64 container with Python 3.14,
Ansible core 2.20.0 and Pyinfra 3.6.1. The image pins primary engines, while base
image and transitive package versions remain floating: a future reproduction
may differ. No SSH or production service was involved. The unchanged role source and two fixture/deploy files are now allowlisted into
a temporary staging tree mounted read-only; no whole-worktree mount remains.
Role logic was not reimplemented for the Ansible side. Fixture execution used
`--network none`; dependency acquisition during image build used the network.

## Contract results

All assertions passed; a final repeat after timeout/fixture cleanup also passed
(about 22:13 UTC, warm build 0.603 seconds). Both engines produced identical initial and rotated file
states, including the existing Ansible provenance header, ordering, options and
comments. Real ephemeral Ed25519 public keys were generated in the container;
private keys never left the disposable container and were never logged. The
fixture tests file state, not successful SSH authentication or sshd syntax.

| Scenario | Ansible seconds / changes | Pyinfra seconds / changes |
| --- | --- | --- |
| First convergence | 0.806 / 2 | 0.253 / 2 |
| No-op | 0.687 / 0 | 0.180 / 0 |
| Repair content + modes + owner/group drift | 0.742 / 2 | 0.193 / 2 |
| Key-set rotation (upgrade of desired state) | 0.748 / 1 | 0.186 / 1 |
| Recovery after rejected inputs | 0.677 / 0 | 0.203 / 0 |
| Disabled with empty inputs | 0.253 / 0 | 0.188 / 0 |

See `results.json` for the exact single-run measurements, failure return codes
and dry-run durations. Empty entries, missing key and blank owner failed before
mutation and preserved the rotated state. A subsequent valid run was a no-op.
Dry runs preserved deliberately drifted state for both tools; the fixture does
not prove equivalent diff presentation or change prediction. Ansible dry-run
change count is predicted; Pyinfra's captured success count represents executed
operations and is zero in dry mode, so these dry counts are not comparable.

"Upgrade" here means replacing the entire key set and removing previous keys.
It is not a package or service upgrade. "Failure recovery" means recovery after
validation rejection, not rollback after interrupted uploads, disk exhaustion,
crash, or failed service health checks. Pyinfra's generic public-file upload is
not evidence of secret safety or the same atomic-write behavior as Ansible's
validated template operation. This role has no private secret input, so SOPS/age
and synthetic secret transport are deliberately out of scope. Prior findings
about unsafe generic sudo upload staging remain unresolved.

Checks: Docker integration twice passed initially and again after review repair;
four safety regressions passed. Python compilation, Black 23.12.1
format check, Ruff 0.1.9 lint and `git diff --check` passed.

## Economics and repair effort

Implementation started approximately 22:07 UTC, first green current-engine
fixture completed at approximately 22:11:45 UTC (about 4m45s wall time).
Documentation and evidence were completed at approximately 22:13 UTC;
format/lint and discoverability/release notes finished at 22:14 UTC (about 7m
implementation/engineering wall time, excluding independent review). This is
agent elapsed time, not human active time or a measured dollar/token cost. The
session exposes neither model billing nor a reliable token attribution; no cost
savings figure is claimed.

Three integration attempts failed in the harness's CLI-output parsing: Pyinfra
uses an operation-oriented results display, then dry mode emits no executed
results. Repair was confined to the test harness (roughly one minute during the
implementation interval); no convergence fix in the Pyinfra implementation was
needed. An initial Debian Python 3.11/Ansible 2.19 setup was replaced before
accepted evidence to align with repository Ansible 2.20 support. Cold image acquisition/build was part of the wall interval but was not
separately retained as a reliable timing; the accepted warm build measured
0.592 seconds. Docker
container startup, assertions and subprocess handling are not included in each
engine invocation duration. One local sample per scenario, no randomization,
Ansible-first execution and shared image caches mean the roughly 3–4x observed
CLI speed difference is descriptive, not a benchmark confidence claim.

## Independent review repair

Sol high round 1 found two valid safety warnings: the initial runner inherited
the selected Docker/build endpoint, and the whole-worktree mount could expose
ignored private files. Both were repaired rather than accepted as limitations.
The runner now rejects non-Unix endpoints before building, validates that the
endpoint is a local socket, pins `docker --host` for build/run/removal, removes
Docker/BuildKit/buildx overrides, and uses legacy build to avoid selected remote
buildx builders. Allowlisted staging excludes ignored secrets, inventories,
keys, unrelated sources and evidence; source symlinks are rejected. Four safety
regression tests cover remote host overrides, remote contexts before build,
local socket/environment handling and ignored-canary exclusion/symlink rejection.
Review repair took approximately two minutes of agent wall time, including
additional safety tests, docs, formatting and actual container rerun. This is
additional to the initial seven-minute implementation interval and excludes the
coordinator's review runtime. A Unix socket is a local endpoint guarantee; it
does not establish the provenance of an operator's deliberately configured
socket proxy or daemon itself.

Round 2 confirmed the runner safety repairs, then found fresh-checkout test
failures when ignored `tmp/` was absent and nested reviewer paths exceeded the
Unix socket bind path limit. The test suite now creates its worktree-local temp
parent and binds the socket by a short relative filename while restoring the
working directory. A copied fresh fixture under an absolute path longer than
108 characters, with no initial `tmp/`, passed all four safety tests, as did the
normal checkout. The malformed README fence was corrected. This test/docs-only
repair took about one minute; Black, Ruff and diff checks passed. No runner or
convergence implementation changed in this round.

## Decision

**Narrow go for another disposable leaf-role experiment; no fleet migration
recommendation.** This current-model slice demonstrates cheap, real local file
convergence with Pyinfra, rather than only mocks. It merits keeping a bounded
trial option open despite the prior Archive result. It does not demonstrate a
lower total maintenance cost: a second implementation introduces duplicate
validation/rendering semantics, engine pin upkeep, CLI result parsing, a new
review/test surface and inventory/secret integration costs. The compact native
file operations avoid custom convergence glue for this particular role.

This extrapolates only to simple fully owned public-file leaf contracts with
existing accounts. It cannot establish economics for apt/package bootstrap,
systemd handlers, rsync application releases, backup/restore, privilege and SSH
transport, multi-host ordering, real SSH key acceptance, or secret-bearing
services. No second role was added because those different contracts require a
separate scoped decision and would dilute this result.

Next decision costs: one fresh model-assisted replication with measured review
repairs; a disposable systemd/package-service role with failure injection; and,
only if secret roles are contemplated, an explicit SOPS/stdin transport threat
model and interrupted-write tests. Inventory/CLI/FastDeploy compatibility and
ownership of any shared helper framework must be costed before a migration
proposal. No production changes are warranted from this result alone.

## Final review and checks

Independent installed `codex-review-loop` runs proved `gpt-6.1-sol` at high
effort in all three rounds. Round 1: two accepted warnings (remote Docker
selection and excessive mount exposure). Round 2: two accepted warnings (fresh
checkout and long socket-path regressions), plus one accepted Markdown
suggestion. All four warnings and the suggestion were fixed. Round 3 returned
CLEAN for the scoped repair delta; no earlier finding remains open. No files
were skipped or truncated, and the review copy excluded none. The harness
redacted part of the synthetic fixture in the text bundle; the complete fixture
was available in its isolated repository copy. This scoped label does not hide
an unreviewed production secret path.

Measured review runtimes were 159.625, 97.995 and 81.650 seconds: 339.270 seconds
(5m39s) total. Initial implementation/docs/checks took approximately seven
minutes; accepted-review repairs took approximately three further minutes.
Overall task wall time from approximately 22:07 to 22:25 UTC was about eighteen
minutes before commit/report. These are agent engineering and review elapsed
measurements, not billing, human labor or fleet-wide cost estimates.

Checks passed: actual Docker convergence comparisons before and after runner
repair, four safety regressions in ordinary and deep fresh checkouts, Black
23.12.1, Ruff 0.1.9, Python compilation and `git diff --check`. The default
collection suite was not run because supported roles were unchanged; the
experiment remains opt-in. The local commit result is reported in the final
Herdr handoff on branch `workspace/pyinfra-trial`; nothing is merged or pushed.
