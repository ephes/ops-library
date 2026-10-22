# Changelog

## Unreleased — software-live Rust port: release 0.1.0 (S7)

- `rust/software-live/release.json` and version 0.1.0 of `software-live`
  and `software-live-apt` (slice S7 of `rust/software-live/PLAN.md`, 7.1,
  7.2, 7.4): the tag `software-live-v0.1.0` publishes
  `software-live-0.1.0-x86_64-unknown-linux-gnu-ubuntu24.04.tar.gz` and
  `…-debian13.tar.gz` (plus `.sha256`), each with `software-live`,
  `software-live-apt`, `LICENSE` and `LICENSE.GPL-3.0`.
- `rust-release.yml` and `rust/scripts/release_checks.py`: a
  `release.json` may declare `shared` binaries. The new job `shared` builds
  them once on the `ubuntu-22.04` runner (glibc floor 2.35), checks them and
  hands them with their sha256 (`release_checks.py checksums`) to every
  variant job, whose `verify` and `pack` accept only that build
  (`--shared-bin-dir`, `--shared-sha256`) and run its `--version` again in
  the variant's image; so both software-live archives carry the same
  `software-live`. The variant jobs build, lint and test only the helper
  (packages `g++ libapt-pkg-dev python3-apt`), check its glibc ceiling and
  `NEEDED` allowlist and run `observe` as an extra smoke command. The build
  and publish jobs now run after a skipped `shared` job; archives are
  written and uploaded from the workspace (paths that also hold inside a
  container job). Crates without `release.json` (metrics-httpd,
  echoport-command-guard) release as before. Nothing installs the release;
  no inventory pins it yet (S8).
- Released: the GitHub release `software-live 0.1.0` (tag
  `software-live-v0.1.0`, commit `98c68001`) has the archive sha256
  `89c940d73ab5eaf6c7064e1b5d4974b54783ed0891076cfdb50b2478ca00c765`
  (`ubuntu24.04`) and
  `9a233b5e6711033f06b8c7998a95d94a90a7870a6472696c3970fbd78b58baa3`
  (`debian13`); `software-live` is 3,464,320 bytes (the same file in both,
  budget 6 MiB), `software-live-apt` 464,144 / 461,984 bytes (budget 2
  MiB), every binary at most `GLIBC_2.34`. GitHub's `/releases/latest` now
  answers with this release despite `--latest=false`; pins never use it.

## Unreleased — software-live Rust port: parity harness

- `rust/software-live/parity/` (slice S5 of `rust/software-live/PLAN.md`,
  section 6.2): `run_parity.py` runs `software_live.py` and the Rust
  release binaries side by side as root in throwaway `ubuntu:24.04` and
  `debian:13` containers — `validate` for the policy matrix, the `serve`
  start-up matrix, every raw endpoint request of `fixtures/serve.json`
  against both live servers with the real `htpasswd`, `export-inventory`
  with real root ownership, and `collect` on a real host (fake Traefik and
  PostgreSQL processes, `systemctl`/`pg_lsclusters` shims, GitHub and
  endoflife.date over HTTPS on loopback through `/etc/hosts` and a
  throwaway CA in the system trust store, APT on real lists and the fake
  repositories), including cache and state cross-reads and the
  software_estate reader on the Rust projections. CI runs it as the last
  step of the `software-live-apt` job; locally `just
  rs-software-live-parity` (Docker). The comparator's tests run in the
  workspace job.
- Fix found by it: the Rust endpoint takes at most 99 header lines, as
  Python's `http.client` does, and refuses every request head over 64 KiB
  with 431 however the bytes arrive (hyper alone let heads of up to about
  128 KiB through when they came in one read). PLAN.md 4.2 item 2 lists
  the head limits exactly. Nothing installs or runs the binary; the
  `software_live` role is unchanged.

## Unreleased — echoport_remote_command_guard: root-run mutations on file descriptors (H1)

### Security

- `echoport_remote_command_guard`: the guard no longer runs `chmod
  0600|0700`, `chown [-R]`, `mv` (both forms) and `rm -f <db>-wal <db>-shm`
  as root on the pathname it checked. A local user who can write inside a
  policy root (the root's service user, e.g. `gotosocial` in
  `/var/lib/gotosocial`) could swap the path, or a directory on it, for a
  symlink between the check and the tool's system call and have root
  change the mode or owner of a file outside the root, or rename or remove
  one there (service user → root). The guard now makes these changes itself:
  it opens `/` and each directory of the path with `O_NOFOLLOW|O_DIRECTORY`
  (a symlink anywhere on the path is refused) and changes, renames or
  removes the entry relative to the directory it opened (`fchmod`/`fchown`
  on an `O_NOFOLLOW` descriptor of the inode `lstat` saw, one link for a
  regular file; `renameat`, or `renameat2(RENAME_NOREPLACE)` when the target
  must not exist; `unlinkat`; `chown -R` one open directory per level,
  symlinks in the tree neither followed nor changed). `chmod`, `mv` and `rm`
  run as the root's owner (the guard drops to that user first), so the
  kernel checks them with that user's own rights; `chown` keeps root.
  `check()` also
  requires each changed path to lie inside its root as written. Work item
  `echoport-guard-toctou-hardening`, slice H1 of
  `rust/echoport-command-guard/PLAN.md` (4.5, R12).
- Runner-facing: the commands the runners send are allowed as before and
  succeed with exit 0 and no output. A failed change is exit 1 with
  `echoport-remote-command-guard: command not allowed` on stderr (before:
  the tool's message) and a `refused from` log line with the reason
  (before: `allowed from`). Stricter than the tools: a symlink on a changed
  path is refused even when it resolves inside the root, a regular file with
  more than one link and special files are not changed, `chmod` of a
  root-owned file and `mv`/`rm` inside a root-owned directory fail (as with
  any change the root's owner may not make; `mv`/`rm` of an entry in a
  directory the owner can write follow that directory's permissions, as
  `rename`/`unlink` do; also `chmod` of a file and `mv`/`rm` in a directory
  the owner cannot read, which the guard opens for reading), `chown -R` leaves
  symlinks' own owners alone, and `mv` never moves into an existing target
  directory or across filesystems. The `echoport_backup` runners' tests pass
  unchanged.
- The hosts get the hardened guard with the next role run (`just
  pin-deploy-backup-key <host>` in ops-control); the ops coordination rolls
  it out together with the `.timeout` runner change.

### Rust ports

- `rust/echoport-command-guard` 0.2.0: the same hardening in the Rust guard
  (`src/mutate.rs`, the `Mutation` decision with an empty `argv` in
  `--decide`/`--shadow` records), Layer-1 fixtures regenerated from the
  hardened Python guard (`fixtures/GUARD_SHA256`), the race table
  `parity/races.json` that both guards run (`parity/races.py`,
  `tests/mutations.rs`; as root in the Layer-2 containers), mutation
  scenarios in Layer 3 and the role's molecule verify. 0.2.0 is the first
  release a host may get (S9); 0.1.0 is never installed. The guard role's
  molecule scenarios install 0.2.0 built from the checkout. Released by the
  tag `echoport-command-guard-v0.2.0` (`966d178e`):
  `echoport-command-guard-0.2.0-x86_64-unknown-linux-gnu.tar.gz`, sha256
  `24bd2a52b1c2aed194ac642fbb0f41e377c47a84a4c94536167ca5f513adec4f`,
  stripped binary 705,952 bytes, highest glibc symbol version `GLIBC_2.34`.

## Unreleased — software-live Rust port: endpoint

- `rust/software-live` gets `serve` (slice S4 of
  `rust/software-live/PLAN.md`): the authenticated JSON endpoint of
  `software_live.py` on hyper 1 and a current-thread tokio runtime, behind
  a small `Endpoint` boundary (bind check, Basic auth, server loop). Same
  contract as Python (GET of the exact path, 404 before auth, 401 with
  `WWW-Authenticate`, the state re-read per request through
  `with_freshness`, 503 when missing or invalid, no request logging);
  documented divergences in PLAN.md 4.2 items 1, 2 and 14 (HTTP/1.1 framing,
  up to 16 connections at a time with the request head due within 5 s and
  the password check, on a blocking thread, stopped after 5 s, the endpoint
  configuration checked at startup).
- `htpasswd -vi` is reproduced in process (bcrypt through the `bcrypt`
  crate) with Apache's password, file and comparison rules; new fixture
  `htpasswd.json` with the real `htpasswd` verdicts of Debian 13 and Ubuntu
  24.04, recorded by `fixtures/htpasswd.py` in containers. New fixture
  `serve.json` runs the Python endpoint's startup and request handling.
  Nothing installs or runs the binary; the `software_live` role is
  unchanged.

## [2.66.1] - 2026-10-22

### Fixed

- `homeassistant_deploy`: normalize surrounding conversation prompt whitespace
  the same way as Core's TemplateSelector. YAML block prompts with a final newline
  no longer trigger repeated subentry updates and agent reloads on every deploy.
  Reject whitespace-only prompts during validation.

## [2.66.0] - 2026-10-22

### Home Assistant built-in voice bridge

- Add opt-in core `llama_cpp` provisioning, explicit no-control options, live
  canary and `auto:llama_cpp` pipeline selection. Retire Custom Conversation
  through the HA API before upgrading and rebuild environments containing its
  component or LiteLLM, preserving the separate Matter environment and Python
  trust/security floors. Credentials travel only on stdin. Existing deployments
  retain their legacy behavior unless the built-in bridge is enabled.

## [2.65.0] - 2026-10-22

### opsgate_deploy: Python or the Rust release per launchd unit

- `opsgate_deploy` gets the implementation switch of the opsgate repository's
  `rust/PLAN.md` 10.1 (slice S10): `opsgate_api_impl` and
  `opsgate_runner_impl` (`python`, the default and unchanged behaviour, or
  `rust`), `opsgate_rust_version`, `opsgate_rust_sha256`,
  `opsgate_rust_release_url`, `opsgate_rust_local_archive`,
  `opsgate_rust_install_root` (`/usr/local/libexec/opsgate-rs`),
  `opsgate_rust_keep_versions`, `opsgate_launchd_python_plist_dir` and
  `opsgate_launchd_verify_retries`/`_delay`. New `tasks/rust_binary.yml`
  installs a pinned release whenever a version is set (checksum-verified
  download or local archive, archive members checked, `root:wheel`, never
  modified in place) and validates it by its versioned path before any plist
  points at it: `--version`, `check-config api` as `control_service_user`,
  `check-config runner` as `ops` (only the env-file path is passed) and a
  read-only `check-db`. A rejected release stops the play when a unit runs
  Rust and is a warning with both impls `python`, so it never blocks the
  rollback. Each plist renders the venv command or `bash -lc "cd <dir> &&
  exec <root>/<version>/opsgate serve|runner"`; with both impls `python` the
  plists are byte-identical to before. A changed Python source or venv no
  longer restarts a unit that runs Rust. Every deploy renders the Python
  variant of both plists to `/etc/opsgate/launchd-python/` for the
  emergency rollback without Ansible. New `tasks/verify.yml` checks each
  managed unit (`launchctl print`, `ps`, the API health endpoint) and
  `tasks/prune.yml` then prunes old releases, keeping the pinned, the running
  and each unit's previous version and pruning nothing when the live state
  is unknown. README section "Implementation: Python or Rust" (switch,
  rollback, emergency runbook). Tests `tests/test_opsgate_deploy_impl.py`
  (`just test-opsgate-deploy-impl`, part of `just test`) with plist fixtures
  in `tests/fixtures/opsgate_deploy/`.

### software_live: switch between Python and the Rust release

- `software_live` gets the implementation switch of
  `rust/software-live/PLAN.md` 7.3 (slice S6): `software_live_impl: python`
  (default, unchanged behaviour) or `rust`, with `software_live_rust_version`,
  the per-variant archive checksums `software_live_rust_sha256`
  (`ubuntu24.04`, `debian13`, read from `/etc/os-release`),
  `software_live_rust_keep_versions` and `software_live_rust_shadow`. The
  release is installed with `rust_release_binary` into
  `<install_dir>/releases/<version>/` (with `software-live-apt` and
  `LICENSE.GPL-3.0`) and validated by its versioned path (`validate`, the
  APT helper) before drop-ins point the endpoint and collector units at it.
  `impl: python` removes the drop-ins and restarts the units with Python
  before any Rust task, so a broken release never blocks the rollback. After
  the initial collection the role verifies the running program; only then
  does it move the pins (`software-live` and the `previous` rollback pin,
  which always names the version verified live before) and prune old
  releases, keeping every version the live state names (drop-ins, shadow
  units, loaded commands, and every process of the units, including a
  collector run and its APT child still executing an older release) and
  pruning nothing when that state cannot be read completely. New shadow
  units (`software-live-shadow-collector.service`/`.timer` at `*:7/15`,
  `software-live-shadow-endpoint.service` on `127.0.0.1:9119`) run the
  release next to the production units. New filter plugin
  `plugins/filter/software_live_impl.py`; tests `tests/test_software_live_impl.py`
  (`just test-software-live-impl`, part of `just test`).
- `software_live_remove` also removes the shadow units and their state and
  the implementation drop-in directories.

### software-live Rust port: collect

- `rust/software-live` gets `collect` of `software_live.py` (slice S3f of
  `rust/software-live/PLAN.md`): the policy check, the observation steps in
  the Python program's order (Traefik upstream and Traefik, OS lifecycle and
  OS, PostgreSQL lifecycle and PostgreSQL, APT through the helper),
  `generated_at_epoch` read after the last observation, the atomic state
  write with the group looked up after the collection (the previous state
  stays on an unknown group or a failed write), and the manual stdout mode
  without `--output`. New flag `collect --report-usage`: one stderr line
  with wall time, CPU time and peak memory of the process and its children,
  for the shadow units. Fixtures from the Python program: every step's
  call order and arguments (`fixtures/report.json`) and `collect` end to end
  in recorded worlds with the call log of every host access
  (`fixtures/collect.json`). Nothing installs or runs the binary; the
  `software_live` role is unchanged.

### software-live Rust port: inventory export

- `rust/software-live` gets `export-inventory` of `software_live.py` (slice
  S3e of `rust/software-live/PLAN.md`): the safe source read (root-owned
  export directory and state file, `O_NOFOLLOW|O_NONBLOCK`, one link, not
  group/world-writable, 1 MiB bound), the allowlisted projection and the
  atomic write of S3a (mode 0640, group set through the descriptor,
  `fsync`, rename; the previous projection stays on any failure), with the Python
  program's order of checks and its `inventory export failed: <Class>`
  line. Fixtures from the Python program (`fixtures/export.json`, including
  the real export on disk with root ownership emulated), and
  `fixtures/rust-export.json`, written by the Rust code and read by the
  `software_estate` reader in `tests/test_software_live_rust_fixtures.py`.
  Nothing installs or runs the binary; the `software_live` role is
  unchanged.

### software-live Rust port: APT helper

- New Rust crate `rust/software-live-apt` (slice S3d of
  `rust/software-live/PLAN.md`): the APT observation of `software_live.py`
  (`observe_apt`, `security_packages`, holds, index ages) through
  `rust-apt`, as a separate helper binary licensed GPL-3.0-or-later
  (`LICENSE.GPL-3.0`); `software-live` runs it as a child process
  (`src/apt.rs`) and links no libapt-pkg. `rust/deny.toml` allows
  GPL-3.0-or-later for `rust-apt` and the helper only; the new
  `rust/scripts/release_checks.py apt-isolation` (CI and the release
  `prepare` job) fails when any other member can reach `rust-apt`. Nothing
  installs or runs the helper; the `software_live` role is unchanged.
- CI: the helper is left out of the default `rust` job and built, linted
  and tested in the new `software-live-apt` job inside `ubuntu:24.04` and
  `debian:13`, which also compares it with python-apt (`software_live.py`)
  on a fake APT world. New recipe `just rs-software-live-apt` runs the same
  in Docker.
- The S1 mapping of `apt_pkg.version_compare` to rust-apt's `cmp_versions`
  read past the end of non-NUL-terminated strings (libapt-pkg's
  `CmpFragment` expects C strings); the helper compares NUL-terminated
  copies (PLAN.md 13.4).

### software-live Rust port: OS and PostgreSQL observations

- `rust/software-live` (slice S3c of `rust/software-live/PLAN.md`): the OS
  observation (Python's os-release parser and fallback, lifecycle
  evaluation) and the PostgreSQL observation (`pg_lsclusters` parsing, the
  postmaster's `--version` run through a descriptor pinned to its image,
  identity checks, lifecycle and drift issues), library only until
  `collect` is wired. The `System` trait gains `read_head`, and every child
  process now gets no descriptor of the program beyond its standard streams
  and a passed one, as `subprocess` (`close_fds`) does (new dependency
  `close_fds`). Fixtures `lifecycle.json`, `os.json` and `postgresql.json`
  replay the Python functions' recorded worlds, including the order of
  every probe. Nothing installs or runs the binary; the `software_live`
  role is unchanged.

### software-live Rust port: upstream lookups and caches

- `rust/software-live` gets the upstream lookups of `software_live.py` (slice S3a)
  (latest Traefik release on GitHub, endoflife.date lifecycles) with their
  daily caches, readable by both implementations in both directions;
  HTTPS through ureq/rustls with the system trust store only; the atomic
  JSON write. New fixture `upstream.json` (generated from the Python
  program) and `rust-caches.json` (written by the Rust code; the Python
  drift test runs the Python program on it). Not wired into `collect` yet;
  the role is unchanged.

### software-live Rust port: Traefik observation

- `rust/software-live` gets the Traefik observation of `software_live.py`
  (slice S3b of `rust/software-live/PLAN.md`): `MainPID`, the
  `/proc/<pid>/exe` link checks, hashing and version probes of the installed
  and the running binary, the identity checks and the bounded retry. The
  running image is executed only through a pinned, inherited descriptor
  (`/proc/self/fd/<fd>`), never through the `/proc/<pid>/exe` link. Fixtures
  from the Python program (`fixtures/traefik.json`, with the call order) and
  a Linux test with real processes. `collect` does not use it yet; nothing
  installs or runs the binary.

### software-live Rust port: crate skeleton

- New Rust crate `rust/software-live` in the `rust/` workspace (slice S2 of
  `rust/software-live/PLAN.md`): the command line of `software_live.py`
  (modes, options, exit codes; `--version`), `validate`, policy validation
  and the Python-compatible `policy_sha256`, the report types, summary and
  `with_freshness`, and the `System` trait the observation slices build on.
  `collect`, `serve` and `export-inventory` stop with exit 1 until their
  slices. Nothing installs or runs the binary; the `software_live` role is
  unchanged.
- `rust/software-live/fixtures/generate.py` writes the Rust fixtures from the
  Python program; `tests/test_software_live_rust_fixtures.py` (`just
  test-software-live-rust-fixtures`, part of `just test`) fails when a
  fixture or `TESTMAP.md` no longer matches it. New recipes `just
  rs-software-live` and `just rs-software-live-fixtures`.

### Rust ports: echoport-command-guard release 0.1.0 (S7)

- `rust/echoport-command-guard` (slice S7 of
  `rust/echoport-command-guard/PLAN.md`): the crate version is now `0.1.0`
  and is released by the tag `echoport-command-guard-v0.1.0` through
  `rust-release.yml`: the GitHub release `echoport-command-guard 0.1.0`
  carries `echoport-command-guard-0.1.0-x86_64-unknown-linux-gnu.tar.gz`
  (binary and `LICENSE`, built on ubuntu-22.04, glibc floor 2.35) and its
  `.sha256`: archive sha256
  `300c849c7883275b600054e4e41d457f49d90ec61d116cb2d63dbeea2f4953c9`,
  stripped binary 668,632 bytes (0.64 MiB, budget 2 MiB), highest symbol
  version `GLIBC_2.34`; `rust/echoport-command-guard/README.md` "Release"
  has these values. The role's `shadow` and `rust` molecule scenarios install the
  guard built from the checkout under the crate's version; a role test
  requires the two to match.
- Lean measurements (PLAN.md 8.3): `parity/e2e/lean.py` measures the Rust and
  the Python guard in both Layer-3 containers (median of 20 runs: wall time
  and peak RSS for `--check-policy`, a refusal and an allowed command, plus
  the stripped binary size) and fails over budget; `just
  echoport-command-guard-lean` runs it locally, and the `rust` workflow runs
  it on its x86_64 runner only when started by hand (`workflow_dispatch`).
- Security review of the whole crate (PLAN.md R2): no acceptance drift; one
  race the Python guard has as well. The root-run `chmod 0600|0700`, `chown
  [-R]`, `mv` and `rm -f` of `-wal`/`-shm` are checked on the resolved path
  and executed as root on the original pathname, so a service user who can
  write inside a policy root can swap in a symlink and redirect them outside
  it. Accepted for 0.1.0 only (owner decision 2026-10-21) and documented in
  the role README and PLAN.md 4.5/R12. The hardening slice H1 (work item
  `echoport-guard-toctou-hardening`, Python guard first, then Rust) must be
  merged and released before any Rust guard install (S9); 0.1.0 is installed
  nowhere and must never be.

### Rust ports: metrics-httpd role switch of four more endpoints (S5b)

- `metrics_endpoint`, `os_apt_maintenance`, `dns_deploy` (DDNS status
  endpoint) and `openclaw_deploy` (metrics endpoint) use the internal helper
  `metrics_httpd_switch` (slice S5b of `rust/metrics-httpd/PLAN.md`, argv of
  section 7.3): new `metrics_endpoint_impl`,
  `os_apt_maintenance_endpoint_impl`, `dns_ddns_status_endpoint_impl` and
  `openclaw_metrics_endpoint_impl` (default
  `{{ metrics_httpd_impl | default('python') }}`). `rust` runs the pinned
  `metrics-httpd` release in its `script` (`metrics-endpoint`), `apt-state`
  (`os-apt-maintenance-endpoint`) or `json-file` mode (`ddns-status-endpoint`
  with the updater's missing-file message and a 10 s request timeout;
  `openclaw-metrics-endpoint` with the collector's missing-file message)
  through the drop-in `metrics-httpd-impl.conf`; it needs
  `metrics_httpd_rust_version` and `metrics_httpd_rust_sha256`. With the
  default `python` the deploy renders exactly the same units and scripts as
  before and changes nothing on the host; it now also checks after each
  deploy that the unit runs the Python script and answers 401 with its
  realm. `os_apt_maintenance` selects the implementation only with
  `os_apt_maintenance_endpoint_enabled` and after the state file exists (the
  unit's `ReadOnlyPaths=` names it); the DDNS switch runs under
  `--tags ddns`; disabling the OpenClaw metrics endpoint also removes the
  drop-in.
- Tests: `tests/test_metrics_httpd_switch.py` (`S5bConsumerStaticTests`,
  `S5bConsumerRenderTests` with goldens in
  `tests/fixtures/metrics_httpd_switch/<role>/`, and a switch run under a
  tagged include; a Python unit with a host-name bind keeps deploying with
  the probe skipped, the verify behaviour S5c added).

### Rust ports: metrics-httpd switch for logyard and static sites (S5c)

- `logyard_deploy` and `static_site_deploy` (slice S5c of
  `rust/metrics-httpd/PLAN.md`, section 7.3): new `logyard_health_impl` and
  `static_site_impl` (default `{{ metrics_httpd_impl | default('python') }}`)
  select the health endpoint's and the static site's HTTP server through
  `metrics_httpd_switch`: `rust` runs `metrics-httpd logyard-health` (the
  unit's `LOGYARD_*` environment) or `metrics-httpd static --bind --port
  --root` from the drop-in `metrics-httpd-impl.conf`; its `--check-config`
  runs as the unit's user with the unit's own `[Service]` lines (logyard: its
  `Environment=` lines exactly as rendered; static: the full hardening incl.
  `MemoryDenyWriteExecute=` and `RestrictAddressFamilies=`). With the default
  `python` both roles render exactly the same unit and script as before; the
  deploy now also checks that the unit runs the Python script and answers
  (logyard: 200 with a JSON `status`; static: 200 for `/`) and moves the
  metrics-httpd pin. These roles are the Ansible path and the rollback engine
  of the pyinfra-deployed `logyard` and `benchmarks_static` services.
- `static_site_deploy`: `static_site_systemd_unit_name` no longer accepts a
  dot (it is also the switch's pin name). The service, the Traefik route,
  the handler flush and the checks now run in one block that carries the
  switch inputs, in the same order as before.
- `metrics_httpd_switch`: new `metrics_httpd_switch_probe_timeout` (default
  `5` s, as before); `logyard_deploy` raises it to three Loki request
  timeouts plus one `systemctl` timeout per listed unit plus 5 s, since the
  health endpoint answers only after those calls. verify skips the probe with
  a message when the bind address is a host name (e.g. `localhost`, which
  only a Python unit accepts) instead of failing on it.
- Tests: `tests/test_metrics_httpd_switch_logyard_static.py` (in `just
  test-metrics-httpd-switch`), goldens in
  `tests/fixtures/metrics_httpd_switch/{logyard_deploy,static_site_deploy}/`;
  `tests/test_logyard_deploy.yml` checks the impl default and the drop-in.

## [2.64.5] - 2026-10-21

### Security

- Add a guarded security-only Rustup 1.29.2 manager/proxy patch entrypoint that
  preserves existing coding toolchains and settings; use patched OS trust and
  pinned official updater checksums instead of the old embedded downloader.

## [2.64.4] - 2026-10-21

### Fixed

- `container_ca_activate`: allow a bounded 600-second native-owner health
  convergence budget for both activation and automatic recovery, retaining
  native health requirements and the legacy non-owner path.

## [2.64.3] - 2026-10-21

### Security

- `container_ca_activate`: Persist CA-only overrides through existing systemd Compose owners, with guarded start/reload, explicit hash-approved reconciliation, and bounded recovery without restarting Docker.

## Unreleased — Rust ports: metrics-httpd release 0.1.0 (S4)

- `rust/metrics-httpd` (slice S4 of `rust/metrics-httpd/PLAN.md`): the
  crate version is now `0.1.0` (`metrics-httpd --version` prints
  `metrics-httpd 0.1.0 (<commit>)`) and is released by the tag
  `metrics-httpd-v0.1.0` through `rust-release.yml`: the GitHub release
  `metrics-httpd 0.1.0` carries
  `metrics-httpd-0.1.0-x86_64-unknown-linux-gnu.tar.gz` (binary and
  `LICENSE`, built on ubuntu-22.04, glibc floor 2.35) and its `.sha256`:
  archive sha256
  `7befbd0f4151d6eb11009d7a93a7e7defbd4559cb0c2086915fa598c6d85fc27`,
  stripped binary 2,249,216 bytes (2.14 MiB, limit 4 MiB), highest symbol
  version `GLIBC_2.34`. `rust/metrics-httpd/README.md` has a "Release"
  section with these values. GitHub shows this first release of the
  repository as "Latest" despite `--latest=false` (no other release to
  fall back to); `rust/README.md` notes that nothing may resolve a binary
  through "latest". No role pins the release yet (S5a–S5e); nothing is
  installed anywhere.

## Unreleased — Rust ports: metrics-httpd parity harness and shadow comparer (S3)

- `rust/metrics-httpd` (slice S3 of `rust/metrics-httpd/PLAN.md`):
  `parity/run_parity.py` runs the rendered Python endpoint scripts (CPython
  3.12, as on the hosts) and the Rust binary side by side as processes on
  loopback and compares their live answers for every gate, json-file,
  script, apt-state, logyard-health and static fixture case, plus
  keep-alive, concurrent requests,
  the slow-client difference D-1 (the single-threaded scripts stall, Rust
  answers), the SIGTERM exit codes and credential-free logs. New recipe
  `just rust-parity-metrics-httpd`; the `rust` CI job installs
  `apache2-utils`, runs the harness and now also runs when an endpoint
  script under `roles/**/*httpd*` changes. `parity/shadow_compare.py` is the
  stdlib comparer for the 24 h shadow run (PLAN.md 10.3): probes both
  shadows of every endpoint, accepts only the allowed differences of
  PLAN.md 5.2, writes counts and differing keys (no payloads, no
  credential) to a JSONL report, records the units' memory, and has
  `preflight` and `summary` commands; tested against fake pairs and, in
  the harness, against the live pairs. No role behaviour changes; nothing
  is installed anywhere.

## Unreleased — Rust ports: echoport-command-guard role switch (S6)

- `echoport_remote_command_guard` (slice S6 of
  `rust/echoport-command-guard/PLAN.md`, section 6.2): new impl selector
  `echoport_remote_command_guard_impl` (`python`, the default, `shadow` or
  `rust`). With `python` and no `echoport_remote_command_guard_rust_version`
  nothing changes: the forced command is byte for byte the old one. A set
  `rust_version` installs the Rust guard through `rust_release_binary` under
  `/usr/local/lib/echoport-command-guard/<version>/` (also with impl python,
  for a quick switch), asserts that root owns every path component and
  nobody else can write it, and runs the Rust `--check-policy` on the
  rendered policy before it is installed; the Python guard stays installed
  and always validates the policy. With impl python every Rust step only
  warns (a broken release never blocks a rollback); with shadow or rust it
  stops the play before the forced command is published. `shadow` publishes
  `<bin> --shadow <policy> <python> -I <guard> <policy>`, `rust` publishes
  `<bin> <policy>`.
- New `tasks_from: confirm_live.yml`, for the playbook to include after its
  post-probe: it verifies that the pinned key's `authorized_keys` line
  carries exactly the published forced command, protects every Rust version
  any line names (a mention of the install root in another form, or an
  unreadable file, skips the prune), then moves the `rust_release_binary`
  pins (impl python keeps the last Rust version as the previous pin) and
  prunes. The main tasks never pin or prune. New filters
  `echoport_guard_live_state` and `echoport_guard_path_chain`
  (`plugins/filter/echoport_guard.py`); new variables
  `echoport_remote_command_guard_authorized_keys_path` and
  `echoport_remote_command_guard_confirm_public_key`.
- Tests: `tests/test_echoport_remote_command_guard_role.py` (in `just
  test-echoport-remote-command-guard`); molecule scenarios `default`
  (python), `shadow` and `rust` on Ubuntu 24.04 and Debian 13 with the guard
  built from the checkout (`rust/echoport-command-guard/parity/e2e/build-local-archive.sh`),
  and `pins` (stub releases: repeated failed deployments, stale and
  unverified lines, live-state protection, the switch to Python, check mode,
  rollback independence). Nothing is deployed; ops-control wiring is S8.

## Unreleased — Rust ports: metrics-httpd logyard-health mode (S2d)

- `rust/metrics-httpd` (slice S2d of `rust/metrics-httpd/PLAN.md`): the
  `logyard-health` mode now serves the payload of
  `logyard_deploy`'s `logyard_health_httpd.py`: Loki readiness and the two
  `count_over_time` ingest windows (a `hyper-util` http client: no
  redirects, a timeout per exchange, answers capped at 64 MiB), `systemctl
  show` per unit of `LOGYARD_HEALTH_UNITS_B64` (parsed once at startup with
  the script's rejection reasons), the ok/warning/critical status, and no
  log line per request. Where the script crashes (non-object Loki answers,
  disconnects, non-UTF-8 output, a NUL in a unit name) Rust reports the
  error in the payload instead (D-2). `--check-config` now also fails on a
  units list with rejected entries. `int()`/`float()` of the `LOGYARD_*`
  numbers no longer accept U+001C–U+001F as white space (Python refuses
  them). New fixture family `logyard_health.json` from the rendered script
  with a fake Loki and a test-only fake `systemctl`
  (`fixtures/fake-bin/systemctl`), replayed by `tests/logyard_health.rs`;
  `tests/test_metrics_httpd_fixtures.py` checks that every Rust difference
  names a PLAN.md 5.2 item. Nothing installs the binary; no role behaviour
  changes.

## Unreleased — Rust ports: metrics-httpd role switch (S5a)

- New internal helper role `metrics_httpd_switch` (slice S5a of
  `rust/metrics-httpd/PLAN.md`, section 7.2): `tasks_from: select` installs
  the pinned `metrics-httpd` release through `rust_release_binary` when
  `metrics_httpd_rust_version` is set, runs its `--check-config` as the
  unit's user in the unit's sandbox (`systemd-run`), and selects the
  implementation with the drop-in
  `/etc/systemd/system/<unit>.service.d/metrics-httpd-impl.conf` (present
  only for `rust`; removed first for `python`); `tasks_from: verify` checks
  after the restart that the unit runs the selected implementation
  (`/proc/<pid>/exe` or the Python script in the command line) and that an
  unauthenticated request gets the expected answer (401 with the realm),
  then moves the unit's pin and prunes old releases. A failure stops the
  play for `rust` and only warns for `python`; no credential is used. New
  filters `plugins/filter/metrics_httpd.py`.
- `backup_metrics_endpoint`, `storage_metrics_endpoint`,
  `thermal_metrics_endpoint`, `tailscale_metrics_endpoint`,
  `dns_metrics_endpoint`: new `<role>_impl` (default
  `{{ metrics_httpd_impl | default('python') }}`) with the argv of PLAN.md
  7.3. With the default `python` the deploy renders exactly the same unit
  and script as before and changes nothing on the host; it now also checks
  after each deploy that the unit runs the Python script and answers 401
  with its realm. `rust` needs `metrics_httpd_rust_version` and
  `metrics_httpd_rust_sha256` (released by S4).
- Tests: `tests/test_metrics_httpd_switch.py` (`just
  test-metrics-httpd-switch`, in `just test`).

## Unreleased — Rust ports: metrics-httpd json-file mode (S2a)

- `rust/metrics-httpd` (slice S2a of `rust/metrics-httpd/PLAN.md`): the
  `json-file` mode now serves the JSON file like the eight Python scripts it
  replaces (backup, storage, thermal, tailscale, dns, openclaw, ddns and
  ops-control's torrent-vpn): the `meta` block (replaced, or merged for
  dns), `json.dumps(..., sort_keys=True)` bytes, 503 `metrics_file_missing`
  with the variant's message, 503 `read_error`, 502 `invalid_json`, and
  answers where Python's handler drops the connection (top-level value not
  an object, invalid UTF-8, ints over 4300 digits; PLAN.md D-2/D-5). Each
  5xx answer writes one cause line to stderr (D-9). New fixture family
  `json_file` in `rust/metrics-httpd/fixtures/generate.py`: the eight
  scripts served on loopback through 39 file states and five gate cases,
  replayed by the Rust tests; the torrent-vpn script is read from an
  ops-control checkout (`METRICS_HTTPD_OPS_CONTROL`, a sibling
  `ops-control` or `~/projects/ops-control`), otherwise its committed cases
  are kept and `tests/test_metrics_httpd_fixtures.py` reports a skip. The
  plan gains the D-4 writer audit (section 5.3): no writer emits `NaN`,
  `Infinity` or lone surrogates today; backup, thermal, storage and
  openclaw could in principle. No role behaviour changes; nothing is
  installed anywhere.

## Unreleased — Rust ports: metrics-httpd apt-state mode (S2c)

- `rust/metrics-httpd` (slice S2c of `rust/metrics-httpd/PLAN.md`): the
  `apt-state` mode now serves the os_apt_maintenance state file like
  `os_apt_maintenance_httpd.py.j2`: the `meta` block with
  `state_file_fresh`, `state_max_age_seconds` and `state_reboot_required`,
  the `summary` (last run, freshness, `overall_ok`) and the reboot state of
  `reboot_state()` (live flag plus the persisted kernel signal; the flag
  file and `uname` are read per request), with exact integer arithmetic.
  Where the Python handler crashes (a `reasons` value `in` cannot search, a
  top-level value that is not an object, invalid UTF-8) Rust answers with a
  JSON error (D-2), and every 5xx gets one error line on stderr (D-9).
  `EndpointRebootStateTests` is ported to Rust unit tests; the new fixture
  family `apt_state` (`fixtures/apt_state.json`, replayed by
  `tests/apt_state.rs`) records the rendered script's `reboot_state()` and
  its handler's answers for 47 state files, and
  `tests/test_metrics_httpd_fixtures.py` checks that every Rust/Python
  difference there is a named error answer. No role behaviour changes.

## Unreleased — Rust ports: rust_release_binary install helper (F3)

- New internal helper role `rust_release_binary` (slice F3 of
  `rust/PLAN-foundation.md`, section 6.2) for the pinned release binaries of
  the Rust ports, included with `tasks_from`: `install` (checksum-verified
  download or local archive, exact regular-file member check, staging and
  `mv --no-target-directory` into `/opt/<crate>/<version>/`, `--version`
  validation as an unprivileged user, never replaces an installed version;
  on failure it removes only its own fresh install and either stops the play
  or warns with `rust_release_binary_failed` so a Python rollback is never
  blocked), `pin` (`.pins/<consumer>` plus the rollback pin
  `.pins/<consumer>.previous`, which moves only when the consumer pins a new,
  verified version) and `prune` (keeps the newest `keep_versions`, every
  current and previous pin of every consumer and every version in the
  consumer's live-state `protect` list, which also takes executable paths
  such as `/proc/<pid>/exe` of a still-running oneshot run; deletes nothing
  when the live state is marked unknown, after a failed install of the crate
  in the same run, when the root or `.pins` cannot be listed completely, or
  when a pin or protect entry cannot be interpreted).
  The decisions live in the new filter plugin `plugins/filter/rust_release.py`.
  New `tests/test_rust_release_binary.py` (`just test-rust-release-binary`,
  part of `just test`) with filter unit tests and localhost
  `ansible-playbook` runs, including the owner's 2026-10-21 cases (v1 → v2 →
  v1 → v3 keeps v1 as the previous pin; repeated failed deploys with
  different targets never prune the live version). No role uses the helper
  yet; `rust/PLAN-foundation.md` 6.1/6.2 now describe the previous pin, the
  `protect` input and the fail-closed prune.

## Unreleased — Rust ports: metrics-httpd static mode (S2e)

- `rust/metrics-httpd` (slice S2e of `rust/metrics-httpd/PLAN.md`): the
  `static` mode now serves `static_site_deploy`'s site (the port of
  `static-site-httpd.py.j2`) with `tower-http`'s `ServeDir`: files with
  `Content-Type`, `Content-Length` and `Last-Modified`, `index.html` for a
  directory, Python's 301 for a directory without trailing `/`,
  `If-Modified-Since` → 304, Python's 404 page, 501 for methods other than
  GET and HEAD, and the four `end_headers` headers (`Cache-Control`,
  `Referrer-Policy`, `X-Content-Type-Options`, `X-Frame-Options`) on every
  answer; access lines on stdout as Python writes them. Files are streamed
  in chunks (the response body of all modes is now a boxed body). Allowed
  differences pinned by the new fixture family `static`
  (`fixtures/static.json`, the rendered template on a sample tree): `Range`
  is honoured (206/416, plus `Accept-Ranges`), a directory with only
  `index.htm` and targets with `..` segments get 404, an
  `If-Modified-Since` that is not an HTTP date is ignored (D-11), the 404
  page of a directory without index says "File not found" (D-3), and a NUL
  in the path gets 404 where Python drops the connection (D-2). New
  `parity/static_site.py` compares the Rust binary with the Python server
  on a site directory; run against the deployed benchmark site on staging
  (2026-10-21, `fixtures/static_real_site.json`), every published file had
  the same status, body, type and headers, so the static cutover (S9e)
  stays in the plan. No role behaviour changes.

## Unreleased — Rust ports: metrics-httpd script mode (S2b)

- `rust/metrics-httpd` (slice S2b of `rust/metrics-httpd/PLAN.md`): the
  `script` mode now serves `metrics_endpoint`'s requests past the gate as
  `metrics_httpd.py.j2` does: it runs the metrics script without a shell or
  arguments and answers 200 with its stdout (Python's universal-newline
  translation, no JSON validation), 502 with the stripped stderr or
  "Metrics script failed" for an exit ≠ 0, and 504 after
  `--script-timeout`. Allowed differences pinned by tests: a timeout kills
  the script's whole process group (D-8), the stderr text goes into the
  page body instead of the reason phrase (D-3), a missing or
  non-executable script and non-UTF-8 output get answers where Python
  drops the connection (D-2), stdout is capped at 64 MiB (D-12), and each
  5xx logs one error line (D-9). New fixture family `script`
  (`fixtures/script.json`, generated from the rendered template with real
  fixture scripts) checked by `just test-metrics-httpd-fixtures`. The plan
  now records the newline translation and the script's stdin. No role
  behaviour changes.

## Unreleased — Rust ports: echoport-command-guard parity gate (S5)

- `echoport-command-guard` (slice S5 of `rust/echoport-command-guard/PLAN.md`):
  the parity gate against the Python guard. New decision property tests
  (`tests/decisions.rs`: grammar-aware random commands with the PLAN.md 7.2
  mutations in random virtual hosts, against the Python guard through the
  oracle; Rust may only accept what Python accepts, with the same decision,
  and refusals carry Python's reason outside the PLAN.md 4.4 classes) and
  the decision invariants (`tests/common/invariants.rs`). Layer 2 gains the
  decision comparison on real trees (`parity/e2e/layer2_decide.py`: every
  path state of each path-taking shape, the real-tree scp test, runs as
  `nobody`, random trees). New Layer 3 (`parity/e2e/layer3_sshd.py`, `just
  echoport-command-guard-layer3`): the Python, Rust and shadow forced
  commands through sshd on Ubuntu 24.04 and Debian 13 with every runner
  command, real scp/rsync transfers, redirects, refusals, SFTP and the
  locale cases, compared on exit codes, output, files, the exec'd tools'
  argv/environment/fds/signals/umask and the syslog lines. New cargo-fuzz
  targets (`fuzz/`, `just echoport-command-guard-fuzz`) for the prefilter
  and tokeniser, `check()`, the policy loader and `repr`, run for an hour
  each with the corpus committed. The PLAN.md 4.4 classes are reviewed in
  the crate README; `parity/allowed_differences.json` stays empty. No guard
  behaviour changes; nothing is installed anywhere.

## Unreleased — Rust ports: echoport-command-guard rules with filesystem (S3b)

- `echoport-command-guard` (slice S3b of `rust/echoport-command-guard/PLAN.md`):
  `check()` now decides the remaining branches of the Python guard, in
  Python's order and with Python's refusal reasons, through the filesystem
  helpers of S2: the raw `umask 077 && tar …` shape (the private media
  archive, umask `077`) and `umask 077 && cat > …` (the restore dump as a
  created stdout redirect), `scp -f/-t` (uploads as `runuser -u <owner>`),
  the three rsync server forms (receivers as the root's owner), `rm -f` of
  SQLite `-wal`/`-shm` files, the snapshot `cat` (a stdin redirect owned by
  the service user), `sha256sum`, `readlink -f`, `test`, `mv`, `mkdir -p`
  (as the root's owner), `chmod` and `chown`. An unbalanced quote in the
  `tar` shape, where the Python guard crashes, is refused as an unparsable
  command. Every Layer-1 fixture case is now decided: each case Python allows
  (3,505) is allowed with an identical decision, and no branch is pending
  any more. Nothing installs the binary; no role behaviour changes.

## Unreleased — Rust ports: echoport-command-guard filesystem layer (S2)

- `echoport-command-guard` gets its filesystem layer (slice S2 of
  `rust/echoport-command-guard/PLAN.md`): the real `GuardEnv` (`geteuid`,
  `getpwnam_r` through NSS via `nix`, `lstat` with glibc's `strerror` texts),
  a port of CPython's non-strict `os.path.realpath` (`pyrealpath`) and the
  plain-file, private-directory and policy-root helpers of `check()` with the
  Python guard's refusal reasons. `realpath` refuses where Python returns a
  partly resolved path: symlink loops, more than 40 symlink traversals, `lstat` errors
  other than `ENOENT`/`ENOTDIR`, `readlink` errors and link targets that are
  not UTF-8 (`path not checkable`, PLAN.md 4.2). The `soft-canonicalize`
  crate was evaluated against the oracle and rejected (265 of 1,531 probes
  differ, 49 of them resolving inside a tree that Python resolves outside).
  New differential tests against the Python oracle over random virtual and
  real trees (`tests/realpath.rs`; the oracle gets an `os_realpath` op), and
  the Layer-2 container harness `parity/e2e/run-layer2.sh` (`just
  echoport-command-guard-layer2`) that compares `realpath`, `lstat` and user
  lookups as root with Ubuntu 24.04's Python 3.12 and Debian 13's Python
  3.13. The binary now runs on `RealEnv`, replacing S4's placeholder whose
  `lstat`/`realpath` failed closed; the rules that use the helpers come with
  S3b. Nothing installs the binary and no role behaviour changes.

## Unreleased — Rust ports: echoport-command-guard runtime and exec (S4)

- `echoport-command-guard` (slice S4 of `rust/echoport-command-guard/PLAN.md`):
  forced-command mode now runs the Python guard's flow instead of refusing
  everything: interactive sessions refused before the policy is read,
  `policy error` refusals, `check()`, the umask, the redirects (opened with
  `O_NOFOLLOW` relative to a checked private directory, as Python does), the
  `allowed from` log line, and the exec with `PATH = SAFE_PATH`, CPython's
  PEP 538 `LC_CTYPE` coercion, SIGPIPE and SIGXFSZ ignored and CPython's
  `os.execvp` search (no `/bin/sh` fallback, exit 127 with `cannot run`).
  Log lines go to syslog under the Python guard's identifier, facility and
  priorities, with Python's `repr` of the command (undecodable bytes as
  `\udcNN`) cut at 1000 characters. New modes a client cannot reach:
  `--decide <policy>` (the decision as JSON on stdout) and `--shadow <policy>
  <python> -I <guard> <policy>` (logs the Rust decision under
  `echoport-remote-command-guard-shadow`, then execs the Python guard with the
  same PID). New process tests (`tests/flow.rs`, Linux) record what the
  executed command inherits and compare the locale coercion with CPython
  3.12 and 3.13. Until S2 the binary's filesystem lookups fail closed.
  Nothing installs the binary; no role behaviour changes.

## Unreleased — Rust ports: metrics-httpd core (S1)

- `rust/metrics-httpd` (slice S1 of `rust/metrics-httpd/PLAN.md`): the
  command line of all five modes (`json-file`, `script`, `apt-state`,
  `logyard-health`, `static`) with `--check-config` (validates the htpasswd
  file, JSON directory, script, site root and logyard environment without
  binding; exit 0 or 2), the HTTP server core (IPv4/IPv6, request timeout,
  64 connections, graceful SIGTERM, Python's access line), Basic auth with
  the rules of the `htpasswd` binary in process (bcrypt `$2y$`/`$2a$`), a
  `serde_json` formatter that writes `json.dumps(..., sort_keys=True)` byte
  for byte (including `float.__repr__`), the `meta` helpers and
  `TESTMAP.md`. Every mode answers the 501/404/401 gate of the Python
  scripts; the mode bodies arrive with S2a–S2e. New Python oracle
  `rust/metrics-httpd/fixtures/generate.py` with committed fixtures (float
  reprs, JSON round trips, meta, auth decisions with the real `htpasswd`,
  gate answers of the rendered scripts) and test-only htpasswd files; new
  `tests/test_metrics_httpd_fixtures.py` (`just test-metrics-httpd-fixtures`,
  part of `just test`) fails when the fixtures drift from the Python
  scripts or a Rust/Python difference is not an allowed one; new recipe
  `just metrics-httpd-fixtures` regenerates them. The plan records the
  allowed differences found on the way (D-4 nesting depth, D-6 `htpasswd`
  rules, new D-14 request parsing). No role behaviour changes.

## Unreleased — Rust ports: echoport-command-guard rules without filesystem (S3a)

- `echoport-command-guard` (slice S3a of `rust/echoport-command-guard/PLAN.md`):
  `check()` now decides the branches of the Python guard that need no
  filesystem, in Python's order and with Python's refusal reasons: `sudo -u
  postgres` and `runuser -u postgres --` with every PostgreSQL branch
  (`pg_dump`, `dropdb`, `createdb`, `pg_restore` including the scratch
  restore with its `< file` redirect, `psql`), `runuser -u <user> -- sqlite3`
  (`.backup`, `.timeout`, the integrity check), `systemctl`, `curl`, `rm -f`
  of temp dumps, `rm -rf --` of temp dirs, `mktemp`, `du` and the `sh -c`
  probe. The Layer-1 runner now requires every fixture case outside the
  filesystem branches (S3b) to be decided as Python decides, and lets a `p3`
  case differ only when the prefilter refuses it or Python's `check()`
  crashes. Forced-command mode still refuses everything until S4; nothing
  installs the binary; no role behaviour changes.

## Unreleased — Rust ports: echoport-command-guard crate skeleton, policy and tokeniser (S1)

- Add the `echoport-command-guard` crate to the Rust workspace (slice S1 of
  `rust/echoport-command-guard/PLAN.md`): `--version`, `--check-policy` (the
  Python guard's validation and messages, with strict JSON types: duplicate
  keys, `NaN`/`Infinity`, out-of-range numbers, lone surrogates and nesting
  deeper than 127 arrays and objects are refused), the command prefilter (printable ASCII and tab only, no `\` or
  `#`), the tokeniser (`shlex` crate, proven equal to Python's `shlex.split`
  by differential tests against the Python oracle), the `Decision` types,
  the virtual `GuardEnv` and a fail-closed dispatcher that still refuses
  every command; forced-command mode refuses everything and executes nothing
  until S4. New Layer-1 runner over all committed fixtures. `rust.yml` gains
  this crate's steps: Python 3.12 from uv for the oracle tests and the
  fixture drift check (`gen_fixtures.py check` under 3.12 and 3.13, `check
  --record` in the repo venv). The fixture generator now tags numbers
  outside the double range and nesting deeper than 127 as `policy-type` (new
  cases `raw-big-integer`, `raw-nesting-127`, `raw-nesting-128`).
  Nothing installs the binary; no role behaviour changes.

## Unreleased — Rust ports: release pipeline with per-binary tags (foundation F2)

- New GitHub Actions workflow `.github/workflows/rust-release.yml` (slice F2 of `rust/PLAN-foundation.md`): a pushed tag `metrics-httpd-v<semver>`, `echoport-command-guard-v<semver>` or `software-live-v<semver>` builds that crate for `x86_64-unknown-linux-gnu` on `ubuntu-22.04` (glibc 2.35) after fmt, clippy and the workspace tests, checks every binary's glibc ceiling and `NEEDED` libraries and its `--version` line (`<binary> <version> (<commit>)`), packs a deterministic `<crate>-<version>-x86_64-unknown-linux-gnu[-<variant>].tar.gz` with a `.sha256` file and publishes the GitHub release `<crate> <version>` (never marked latest; only the publish job may write). `workflow_dispatch` with a crate runs the same build and checks and keeps the archives as workflow artifacts. New stdlib script `rust/scripts/release_checks.py` (`tag`, `matrix`, `glibc-floor`, `smoke`, `verify`, `pack`) with tests and a two-variant fixture; an optional `rust/<crate>/release.json` declares build variants (container image, apt packages, members to build, archive binaries with their own glibc ceiling, extra `NEEDED` sonames and smoke commands, archive files). Release how-to in `rust/README.md` "Releases". No role behaviour changes; nothing is installed anywhere.

## Unreleased — ca_trust_consumers: Node.js trust in sudo sessions (2.64.2)

- `ca_trust_consumers` with `ca_trust_consumers_node_cli` now also gives sudo
  sessions `NODE_OPTIONS=--use-openssl-ca`: Debian 13's sudo PAM stack does not
  read `/etc/environment`, so `sudo -u <app>` sessions (Ansible/pyinfra
  `become`, e.g. `npm ci`, `yarn install`) lost the flag. A visudo-validated
  sudoers drop-in sets `Defaults env_file=` to a root-owned file with the same
  merged value; a caller's own `NODE_OPTIONS` is never passed through. The
  effective policy is read with sudo's own `cvtsudoers -f json` before and
  after the change: any `env_file` other than exactly one unbound entry for the
  role's file (scoped, negated, foreign, duplicated) or an unexportable policy
  makes the role fail.
  `ca_trust_consumers_node_cli_sudo: false` turns this off.

## Unreleased — opsgate_deploy leaves the Rust port out of the Python app dirs

- `opsgate_deploy`: `opsgate_rsync_excludes` gains `/rust/`, so the source
  sync no longer copies the opsgate repository's Rust port workspace (sources,
  plans and, after a local `cargo build`, gigabytes of `rust/target/`) into the
  API and runner app directories. The pattern is anchored to the top of the
  checkout; a nested directory named `rust` still ships. A `rust/` an older
  role version already synced stays in place (`rsync --delete` never removes
  excluded paths) and is inert. New `tests/test_opsgate_rsync_excludes.py`
  (`just test-opsgate-rsync-excludes`) runs the role's own sync tasks with its
  defaults in check mode against a temporary opsgate-shaped checkout.

## Unreleased — graphyard_deploy: Python/Rust agent selector

- `graphyard_deploy`: new `graphyard_agent_impl` (`python`, the default, or
  `rust`) with `graphyard_agent_rust_version`, `_sha256`, `_release_url`,
  `_local_archive`, `_install_root` (`/opt/graphyard-agent`) and
  `_keep_versions` (3), per section 8.3 of graphyard's `agent-rs/PLAN.md`. A
  pinned version is installed after the migrations into
  `<root>/<version>/graphyard-agent` (sha256-checked download or local
  archive, only the regular files `graphyard-agent` and `LICENSE`, an
  installed version is never replaced) and validated as `graphyard_user`
  with `--version` and `--check-schema --db <django path>/db.sqlite3` before
  anything switches. With `rust` the drop-in
  `graphyard-agent.service.d/agent-impl.conf` replaces only `ExecStart`; with
  `python` it is removed. A version change or switch reloads systemd and
  restarts the agent; afterwards the role checks the live process
  (`/proc/<pid>/exe` for Rust, `manage.py start_agent` argv for Python) and
  prunes old versions, keeping the pinned, live and previously selected ones.
  The default stays Python and installs nothing, so existing deploys are
  unchanged. `graphyard_rsync_excludes` gains `agent-rs/target/`. New
  Molecule scenario (`just test-graphyard-deploy-molecule`) and contract
  tests (`just test-graphyard-deploy-agent`, part of `just test`).

## Unreleased — Rust ports: echoport-command-guard contract fixtures (S0)

- Add the Python oracle and fixture generator for the Rust port of the
  `echoport_remote_command_guard` forced-command guard
  (`rust/echoport-command-guard/parity/oracle.py`, `gen_fixtures.py`) and the
  generated Layer-1 decision fixtures (`rust/echoport-command-guard/fixtures/`,
  about 13.4k cases: every runner command, the live journal shapes, every
  unit-test call, mutations, filesystem states and `--check-policy`
  documents), plus `TESTMAP.md`. `just test-echoport-remote-command-guard`
  now also runs `tests/test_echoport_command_guard_fixtures.py`: the
  fixtures must match the guard's sha256 and regenerate byte for byte
  (runners re-recorded), and the Python guard must accept only printable
  ASCII and tab. New recipe `just echoport-command-guard-fixtures`
  regenerates them after a guard or runner change. No role behaviour changes.

## Unreleased — Rust ports: echoport-command-guard plan

- Add `rust/echoport-command-guard/PLAN.md`, the plan for a Rust port of the `echoport_remote_command_guard` forced-command guard (Python guard as oracle, generated decision fixtures, stricter refusals only, an impl selector `python | shadow | rust` with Python as rollback, shadow runs, staging canary with rollback drills, and Python retirement), including the owner decisions of 2026-10-21. Plan only; no role behaviour changes.

## Unreleased — Rust ports: foundation, metrics-httpd and software-live plans

- Rust foundation (slice F1 of `rust/PLAN-foundation.md`): Cargo workspace under `rust/` (explicit members, pinned toolchain 1.99.1 = MSRV, shared lints and release profile, committed `Cargo.lock`, cargo-deny policy `rust/deny.toml`, MIT `rust/LICENSE`, `rust/README.md`) with the `metrics-httpd` crate skeleton (`metrics-httpd --version` prints `metrics-httpd 0.0.0 (<commit>)`, nothing else yet). New GitHub Actions workflow `.github/workflows/rust.yml` (the repository's first; `rust/**` only, read-only permissions): fmt, clippy `-D warnings`, `cargo test`, cargo-deny and the `rust/scripts` tests; `[workspace.metadata.ci] exclude` (via `rust/scripts/ci_excludes.py`) can leave a crate with special build dependencies out of that job. New `just rust-check` and `just rust-test` (not part of `just test`). `galaxy.yml` `build_ignore` now excludes `rust` and `.github`, so a collection built from a checkout never packs `rust/target/`; `tests/test_collection_build_ignore.py` (`just test-collection-build-ignore`, part of `just test`) builds the collection and checks it. No role behaviour changes.
- Add `rust/PLAN-foundation.md` (shared Cargo workspace under `rust/`, toolchain and cargo-deny policy, CI, per-binary release tags such as `metrics-httpd-v0.1.0`, glibc 2.35 floor, collection `build_ignore`, and the shared install helper for pinned release binaries) and `rust/metrics-httpd/PLAN.md` (Rust replacement for the Python HTTP endpoint daemons of the `*_metrics_endpoint`, `metrics_endpoint`, `os_apt_maintenance`, `dns_deploy`, `openclaw_deploy`, `logyard_deploy` and `static_site_deploy` roles). Both plans record the owner decisions of 2026-10-21 (first GitHub Actions workflows, coordinator-made collection releases, static site as the last cutover, 7-day Python retirement, the separate GPL `software-live-apt` helper, up to three review rounds). Plans only; no role behaviour changes.
- Add `rust/software-live/PLAN.md` (Rust replacement for the `software_live` collector, endpoint and inventory export; MIT main binary plus the separate GPL `software-live-apt` helper per distribution variant, with a CI dependency-graph check that keeps `rust-apt` out of every other member; role switch through `rust_release_binary` with a live-state `protect` list and a `previous` rollback pin, shadow units, staged cutover and a 7-day soak before the Python retirement). Plan only; no role behaviour changes.

## Unreleased — Home Assistant integration downloads use the system CA store (2.64.1)

- `homeassistant_deploy`: new `homeassistant_uv_system_certs` (default `true`)
  installs a managed drop-in with only `Environment=UV_SYSTEM_CERTS=1`, so
  Home Assistant's bundled uv (integration requirement installs) trusts the
  patched operating-system CA store instead of its built-in roots, which for
  Home Assistant 2026.7.2 (uv 0.11.25) still include emSign ECC Root CA - G3.
  Before any change it refuses existing trust settings (unit, unit file,
  service-manager environment or running service), EnvironmentFiles, other
  drop-ins and a system store that still holds a distrusted root; its own
  managed setting is accepted on repeat. New maintenance entry point
  `tasks_from: uv_system_certs.yml` applies only the drop-in to an existing
  service, restarts when it changed, waits for health and verifies. No Home
  Assistant, uv, package or integration-constraint changes.
- `python_security_floor`: new read-only `tasks_from: system_store.yml`.

## Unreleased — certifi/pip deploy-time security floor (2.64.0)

- New `python_security_floor` role and `local.ops_library.uv_lock_floor_violations`,
  `python_security_constraints` and `python_security_report_violations` filters:
  keep certifi at 2026.10.19 or later and upstream pip at 26.2.2 or later across
  normal deploys (eMudhra/emSign CA compromise, GHSA-6q48-6c7w-9gw2). Nothing is
  added to environments without certifi/pip; distrusted roots are matched by
  SHA-256 fingerprint; system-site certifi/pip is accepted only when owned by the
  distribution package and using the system store; explicit trust overrides are
  left alone.
- `metube_deploy`: resolves `metube_repo_version` to one commit in a staging
  checkout (new `metube_source_check_dir` when the UI build is off), refuses that
  commit's `uv.lock` below the floor before the install directory or environment
  changes, checks out exactly that commit, and verifies the environment after
  the sync.
- `homeassistant_deploy`, `open_webui_venv_deploy`, `paperless_deploy`,
  `takahe_deploy`: verify existing environments before changing anything
  (`paperless_deploy` and `takahe_deploy` through `python_security_floor` as
  their first role dependency, ahead of the uv/Redis/PostgreSQL installs), pass a
  constraint file to every package install the role runs, and verify again
  afterwards. Environments below the floor that the role's own installs would
  not raise (for example a stale pip) now fail the deploy before any change:
  remediate them first. Disable per role with
  `<role>_python_security_floor_enabled: false`.

## Unreleased — interrupted trust package recovery (2.63.6)

- Recover explicitly proven interrupted certifi updates with immutable prior-install evidence, exact generated-cache ownership repair and owner-identity offline restoration.

## Unreleased — loopback trust preflight and validation labels (2.63.5)

- Correct OpenClaw trust validation task-name prefixes so strict role lint accepts the incident checks; validation behavior is unchanged.
- Keep LiveKit idle-preflight bearer-token API requests on loopback even when ambient HTTP proxies are configured; exercise the actual CLI under a hostile proxy environment.

## Unreleased — CA trust for Node.js and long-running TLS clients (2.63.4)

- New `ca_trust_consumers` role, for the eMudhra intermediate CA key
  compromise (October 2026): a fixed system CA store does not reach Node.js,
  which verifies against its compiled-in Mozilla store, nor running Go services,
  which load system roots once per process. Behind a CA readiness gate (minimum
  `ca-certificates` version and no forbidden root, by SHA-256, in the bundle,
  `/etc/ssl/cert.pem`, `/etc/ssl/certs` or `/etc/pki/tls/certs`) the role
  - merges `--use-openssl-ca` into `NODE_OPTIONS` in `/etc/environment` for
    login/SSH/sudo/cron sessions (npm, corepack, yarn, deploy tools), keeping
    existing options;
  - adds a `NODE_OPTIONS` drop-in to listed Node.js services (stopped ones
    too, without starting them), keeping the unit's own options, failing
    closed on any `EnvironmentFile=` that mentions `NODE_OPTIONS`, uses a
    wildcard or cannot be read, and checking the effective value (later
    drop-ins, `UnsetEnvironment=`);
  - restarts listed services, one at a time with health checks, only when
    running and started before the CA bundle changed (or, for Node.js
    services, while a running process lacks the flag), never starting a
    stopped unit and refusing restarts that would activate staged binary,
    unit or config changes; a detached `systemd-run` restart covers
    `tailscaled`;
  - verifies the flag in the unit's effective environment and in every
    running Node.js process of the listed services;
  - refuses, before writing anything, when a listed unit already awaits
    `daemon-reload`, and never logs or diffs `/etc/environment` or unit
    definitions (they can hold secrets).
  `--use-system-ca` and `NODE_EXTRA_CA_CERTS` only add roots and leave the
  bundled copy of a distrusted root trusted, so the role does not use them.

## Unreleased — Voxhelm Python trust cache refresh (2.63.3)

- Add an explicit Voxhelm Python trust-cache refresh entrypoint with read-only aggregate idle checks, existing-unit provenance validation, patched certifi TLS probes, and verified launchd child replacement without source deployment.

## Unreleased — legacy trust metadata and check-mode compatibility (2.63.2)

- Keep narrowly scoped trust updates compatible with malformed unrelated legacy dependency metadata while rejecting malformed trust-package constraints. Preserve inherited collection paths in the fresh-host check-mode fixture and prevent fresh AWS drop-in parent failures under check mode.

## Unreleased — bounded container trust activation (2.63.1)

- Add bounded trust-only Compose fleet activation with exact installed image retention, private receipts, recovery, and one Docker daemon restart. Optional `container_ca_activate_livekit_config` performs read-only room/egress idle preflight and requires existing target PyYAML.

## Unreleased — eMudhra macOS and container trust remediation (2.63.0)

- Remediate Apple curl's separate macOS CA bundle with atomic trust-preserving backups and TLS probes.
- Patch explicitly allowlisted macOS Python environments and certifi-only deployed lock records without adding packages.
- Prepare isolated per-image replacement container CA stores; optional Graphyard, Logyard and OpenClaw settings consume them.
- Repair LinuxServer native Qt/OpenSSL trust before application startup, failing closed on unknown trust formats.
- Add supported managed Chrome distrust policy for eight compromised eMudhra keys, covering the browser's independent root store.

## Unreleased — nyxmon_deploy: deploys no longer fail on a vanishing SQLite journal (2.62.2)

- `nyxmon_deploy` no longer fails while the monitoring agent writes. The
  database uses `journal_mode=delete`, so every write transaction creates
  `db.sqlite3-journal` and deletes it at commit. Two tasks lost that race
  (the Rust agent cutover needed three runs): `sqlite_privacy | Restrict
  database and sidecars` listed a journal that was gone when its `file` call
  ran, and `source_rsync | Set ownership for synced files` walked the site
  root recursively and failed on a journal deleted mid-walk.
- The ownership fix now sets owner/group on the site root, lists its entries
  without the transient sidecars (`db.sqlite3-*`) and recurses into each entry
  on its own; top-level symlinks are changed, not followed. The database, its
  agent lock and backups stay in the pass.
- The privacy pass still restricts every `db.sqlite3*` file it finds. A failure
  on a transient sidecar is no longer an error, but the verify pass is
  unchanged: every database file still present afterwards must be the service
  user's and `0600`, or the deploy fails. Failures on the database, the lock or
  a backup fail the deploy as before.
- rsync deploys now require `nyxmon_django_path` to equal `nyxmon_site_path`
  (the Django sync puts the project and `db.sqlite3` there).

## Unreleased — explicit Java fresh-trigger recovery (2.62.1)

- `java_ca_refresh`: explicitly process the distribution Java fresh trigger when
  Ubuntu does not forward `--fresh` to hooks; retain backup provenance and an
  anchored custom-certificate identity baseline across recovery before JVM restarts.

## Unreleased — Linux trust remediation (2.62.0)

- Add narrowly scoped Linux CA and virtual-environment trust remediation with offline verified wheels, dependency preflight, rollback evidence and serial health-checked restarts.

## Unreleased — macOS Java trust copies (2.61.0)

- `macos_java_trust`: maintain fingerprint-filtered JSSE trust copies and explicit
  PyCharm VM options while preserving vendor bundles and unrelated trust. A narrow
  GUI LaunchAgent supplies per-app options without suppressing IDE settings import.

## Unreleased — distribution Java trust refresh (2.60.0)

- `java_ca_refresh`: refresh stale Debian Java trust through distribution hooks
  after patched OS CA updates, then restart only explicitly selected JVMs.

## Unreleased — FastDeploy token issuance admins and restore policies (2.59.0)

- `fastdeploy_deploy`: new `fastdeploy_service_token_admin_users` (list) and
  `fastdeploy_restore_policies` (service name to `{bucket, prefixes}`) write
  FastDeploy's `SERVICE_TOKEN_ADMIN_USERS` and `RESTORE_POLICIES` (FastDeploy
  main `8faa9bd`). Without them FastDeploy refuses API token issuance (403,
  also the web UI deploy button) and every restore (422). Each is written only
  when non-empty, as compact JSON in single quotes in `.env` and `.env.shell`,
  byte-identical to ops-deploy's `FastdeployConfig`. Values that FastDeploy
  would not parse, or that could break the quoting, fail the role before
  `.env` is written. See "Token issuance admins and restore policies" in the
  role README.

## Unreleased — explicit AWS system trust (2.58.0)

- Support an explicit system CA bundle override for allowlisted botocore consumers without certifi, preserving custom trust configuration and serial health-checked restarts.

## Unreleased — maintained Python trust tools (2.57.1)

- Pin uv 0.13.4 with verified Linux/macOS release hashes and matching Home Assistant, MeTube and OpenWebUI installer defaults.
- Update controller certifi to 2026.10.19 for the eMudhra trust incident.

<!-- Historical release notes repeat category headings within a release. -->
<!-- markdownlint-disable MD024 -->

## Unreleased — Traefik ACME storage adoption transaction (2.57.0)

- `traefik_deploy` transactions add the narrow `acme_storage` action: byte-exact
  store copy, resolver-only email/storage repair, source SHA256 and public
  certificate-set checks, pre/post SNI fingerprint comparison, and config rollback.
  Read-only health probes can capture/compare TLS fingerprints; the controller
  offers an offline candidate check. A target that is an exact copy of the
  source (left by a rolled-back attempt) is accepted so a reviewed retry needs no
  manual cleanup; any other target content is still refused. The new
  `health_probe_capture` task entry captures a fresh probe baseline read-only
  from a temporary directory. Validated in a
  native Traefik 3.7.14 VM (success and forced rollback, no CA traffic). No
  production migration has run.

## Unreleased — ansible-core 2.20.3 floor and quiet MeTube uv sync (2.56.0)

- The collection now requires ansible-core >= 2.20.3 (`meta/runtime.yml`
  `requires_ansible`, `pyproject.toml`), and its own lock and test environment
  move from ansible-core 2.20.0 to 2.20.10. ansible-core 2.20.0–2.20.2 write a
  stray `Install-Python-Debian: no` line into deb822 repository files (seen on
  macmini's PostgreSQL apt repo), which newer controllers remove again, so the
  same deploy reported changed whenever the controller version flipped. Note
  that Ansible only warns on a `requires_ansible` mismatch unless
  `collections_on_ansible_version_mismatch = error` is set.
- `metube_deploy`: the `uv sync` task no longer reports changed (and restarts
  MeTube) on every run. Its `changed_when` ended in `or rc == 0` and only read
  stdout, while uv prints its summary to stderr; it now reports changed only
  when uv installs or uninstalls packages.

## Unreleased — No secrets in sudo-logged task environments (2.55.0)

- With `become_user` set to an unprivileged account, Ansible puts every task
  `environment:` value into the command it hands to sudo, and sudo logs that
  command to the journal and `/var/log/auth.log`; `no_log` does not prevent it.
  Several roles passed secrets that way, so they ended up in host logs on every
  deploy. Fixed:
  - `daybook_operations_api_deploy`: `migrate`/`provision_operations` source a new
    0600 `environment.shell` companion (Django secret, database URL, signing
    keyring were logged before).
  - `chesslab_deploy`, `weeknotes_home_deploy`: management commands source a 0600
    `.env.shell` companion; chesslab app-user passwords come from stdin.
  - `echoport_deploy`: `migrate`/`collectstatic` rely on the settings reading the
    0600 `.env`; `ensure_superuser` reads the password from stdin.
  - `fastdeploy_backup`: `pg_dump` reads the password from stdin.
  - `graphyard_auth_bootstrap_deploy`: the bootstrap user's credentials travel
    inside the stdin script.
  - `homeassistant_deploy`: the WebSocket helpers read the API token and the
    Custom Conversation API key as JSON from stdin.
  - `marina_deploy`: `ensure_superuser` reads the password from stdin.
  - `postgres_install`: the admin password is a `login_password` module
    parameter instead of a `PGPASSWORD` environment value.
  - `paperless_deploy`: the superuser bootstrap script, password included, goes
    to `manage.py shell` on stdin instead of a heredoc on the shell command line.
- The service environment templates of the daybook operations API, chesslab and
  weeknotes.home render unchanged for systemd; `task_shell_environment: true`
  renders the shell-quoted companion.
- New guard `tests/test_become_environment_secrets.py`
  (`just test-become-environment-secrets`, part of `just test`): fails on
  secret-looking names or secret-named variables in the environment or command
  line of a task that becomes an unprivileged user. Reviewed exceptions:
  `heis_deploy` admin password (open, outside this change's scope) and the
  non-secret asset-build environments of `metube_deploy` and `wagtail_deploy`.
- Values already logged are not removed by this change; rotate the affected
  secrets and clean the host logs separately.

## Unreleased — Non-exclusive authorized_keys mode and opsgate deploy keys (2.54.0)

- `ssh_authorized_keys_manage` gains `ssh_authorized_keys_manage_exclusive`
  (default `true`, the full-file rendering as before). With `false` the role
  runs `ansible.posix.authorized_key` (`state: present`, `exclusive: false`)
  once per entry: missing keys are appended, a listed key with other options
  or another comment is rewritten in place, and every other line (keys other
  roles installed, comments) stays. The declared line equals the one the
  full-file mode renders, so switching a file rendered by the role is a no-op.
  Before writing, the non-exclusive mode rehearses on scratch copies with the
  module itself and refuses, changing nothing, when the module would rewrite
  lines the role does not declare (merged duplicate keys or identical
  comment/blank lines, rebuilt key lines, CRLF) or when two entries share a
  key. No entry field may contain a line break any more. New
  `tests/test_ssh_authorized_keys_manage.py` (`just
  test-ssh-authorized-keys-manage`) runs both modes against a temporary home.
- `opsgate_deploy` gains `opsgate_ops_github_deploy_keys`: one key pair per
  GitHub SSH workspace repository (read-only deploy keys), installed as
  `~/.ssh/id_github_deploy_<name>` with a `Host github-<name>` alias, and the
  workspace is cloned/fetched as `git@github-<name>:...` (an existing clone's
  `origin` is rewritten). Once deploy keys are configured and the account key
  variable is empty, the old account key files are removed. The deploy-key
  tasks run with `no_log`.
- `opsgate_deploy`: the GitHub SSH URL checks in `validate.yml` and
  `workspace_repos.yml` wrote `github\\.com` inside folded YAML scalars, which
  reached the regex as a literal backslash and never matched. The GitHub host
  key task was therefore always skipped and the "GitHub SSH repos need a key"
  validation always passed. They now use `github[.]com`. New
  `tests/test_opsgate_deploy_keys.py` (`just test-opsgate-deploy-keys`).

## Unreleased — Every SQLite backup waits for writers (2.53.0)

- `echoport_backup`: the SQLite handling of the generic runner (2.51.1) moved
  into the shared `templates/_sqlite_backup.py.j2`, and every other runner that
  copies a SQLite database includes it: `echoport_backup.py.j2` (Echoport's own
  database), `homeassistant_backup.py.j2`, `graphyard_backup.py.j2`,
  `delve_backup.py.j2`, `vaultwarden_backup.py.j2` and
  `marina_staging_backup.py.j2`. Each backup now passes `.timeout 30000` before
  `.backup`, retries a failed backup or integrity check up to 3 times 5 s apart,
  removes a partial copy, requires `PRAGMA integrity_check` to print exactly
  `ok` (the old substring test accepted any report containing "ok", for example
  "broken"), and the failure names the database and the sqlite3 error (the
  `run_cmd` callers used to report only the exit status). The delve and
  Vaultwarden runners used Python's `sqlite3` backup API with its 5 s busy
  timeout; they now use the same `sqlite3` call, and the Vaultwarden runner no
  longer creates an empty database when the source is missing. The
  pre-restore integrity checks use the exact `ok` test too.
- `echoport_backup` GoToSocial runner: the online snapshot on the host sends
  `sqlite3 <db> ".timeout 30000" ".backup '<tmpdir>/<name>'"` and retries up to
  3 times, each attempt into a new file (`retry<N>-sqlite.db`) in the private
  temp dir; the `snapshot` step carries the sqlite3 error.
- `echoport_remote_command_guard`: a `sqlite_snapshots` `.backup` may carry one
  `.timeout <ms>` argument before it (1 to 999999 ms); the old form is still
  accepted. Deploy the guard on the GoToSocial host before the runner.
- `homelab_backup`, `work_app_backup`, `nyxmon_backup`, `homeassistant_backup`:
  the hot `sqlite3 .backup` task passes `.timeout 30000`; `nyxmon_backup` and
  `homeassistant_backup` retry it twice, 5 s apart (homelab and work_app
  already retried and fall back to an offline copy). `vaultwarden_backup` is
  unchanged: it stops the service before its `.backup`.
- The heis and villakunterbunt runners are not changed.
- Tests: new `tests/test_sqlite_backup_runners.py` (in
  `just test-echoport-sqlite-backup`) backs up a real database through each
  local runner while another connection holds its exclusive lock, checks the
  retry, the partial-copy cleanup, the exact `ok`, that no runner template runs
  its own `.backup`, that Ansible's `template` module resolves the include, and
  the four role tasks. `tests/test_gotosocial_echoport_backup.py` covers the
  remote snapshot under a lock, `tests/test_echoport_remote_command_guard.py`
  the new guard shapes.

## Unreleased — Metadata-only MinIO backups (2.52.0)

- `minio_backup`: `minio_backup_include_data: false` makes a metadata-only
  snapshot: IAM export, bucket metadata export (policies, versioning,
  lifecycle, replication config), env file, systemd unit, Traefik/TLS config.
  MinIO is not stopped, no data directory is checked, measured or copied, and
  the disk check only asks for `minio_backup_metadata_min_free_bytes`.
  `metadata.yml` records `scope: metadata` and empty `data_dirs`. The default
  (`true`) keeps the cold full backup unchanged.
- `minio_backup`: `minio_backup_keep_count` (default `0`, keep all) keeps the
  newest N `<prefix>-<timestamp>` snapshots under `minio_backup_root` and
  deletes older ones of the same prefix.
- `minio_restore`: a `scope: metadata` snapshot only re-imports bucket
  metadata and IAM into the running MinIO; no stop, no data rsync, no data
  directory checks. System files come back only with
  `minio_restore_metadata_restore_system_files: true`;
  `minio_restore_allow_metadata_only: false` refuses such snapshots. A full
  restore now refuses to run without a data directory.
- New Molecule scenario `roles/minio_backup/molecule/default` (real MinIO in
  Docker, binaries copied from a MinIO image because dl.min.io no longer
  serves them): metadata-only backup while MinIO keeps running, retention,
  and an IAM restore of a deleted user from that snapshot.

## Unreleased — encrypted_volume_prepare stops rewriting fstab and remounting (2.51.3)

- `encrypted_volume_prepare`: every run rewrote the fstab entry twice and
  remounted the mounted volume. `lineinfile` wrote the line with `0 2`, then
  `ansible.posix.mount` (`state: mounted`, no `dump`/`passno`, so both `0`)
  wrote it back with `0 0`, and a changed fstab entry on a mounted path makes
  the module run `mount -o remount` (macmini: `/mnt/cryptdata` under a running
  MinIO on every `deploy-one minio`). The `lineinfile` fstab task is gone; the
  mount task is the only writer and takes the new
  `encrypted_volume_fstab_dump` and `encrypted_volume_fstab_passno` (default
  `"0"`/`"0"`, the fields the mount task has been leaving on the host). A
  matching entry is not touched and the volume is not remounted; a real change
  (options, source, dump, passno) still rewrites the entry and remounts, so new
  options take effect. A new `file` task keeps `/etc/fstab` `root:root 0644`.
- Validate-only mode: the crypttab/fstab asserts used the string result of
  `regex_search` as a conditional, which current ansible-core rejects; they
  now test `is not none`. The fstab check uses the configured dump/passno
  instead of a fixed `0 2` and accepts `UUID=<uuid>` (what the configure path
  writes) only when the mapper is open and that is its filesystem UUID;
  the mapper path is always accepted.
- New `just test-encrypted-volume-fstab` (part of `just test`): runs the
  role's mount task against a temporary fstab and the validate-only assert.

## Unreleased — Mastodon federation cache tasks pass lint-strict (2.51.2)

- `mastodon_deploy`: the tasks in `federation_cache.yml` and
  `federation_cache_items.yml` now carry their file prefix
  (`federation_cache | ...`, `federation_cache_items | ...`), so
  `just lint-strict` passes again (it reported four `name[prefix]` findings).
  Task names only; behavior is unchanged.

## Unreleased — Generic Echoport runner waits for SQLite writers (2.51.1)

- `echoport_backup`: the generic runner (`backup.py.j2`, used by nyxmon and
  the other `generic_paths` targets) ran `sqlite3 <db> ".backup ..."` without
  a busy handler. A writer committing at that moment holds the exclusive lock
  of a rollback-journal database, and sqlite3 then fails at once with
  "database is locked"; the nyxmon backups of 2026-10-17 and 2026-10-20 failed
  this way (the nyxmon agent commits a check result every few seconds). The
  runner now passes `.timeout 30000` before `.backup`, retries a failed backup
  or integrity check up to 3 times 5 s apart, removes a partial copy, requires
  the integrity check to print exactly `ok`, and appends the sqlite3 error to
  the `Failed to backup database: <path>` step message. New
  `tests/test_echoport_sqlite_backup.py` (`just test-echoport-sqlite-backup`)
  backs up a real database while another connection holds its exclusive lock.

## Unreleased — certbot_dns_deploy removes listed stray config trees (2.51.0)

- `certbot_dns_deploy` gains `certbot_dns_stray_config_dirs` (default `[]`):
  an explicit list of leftover certbot config trees outside
  `certbot_dns_config_dir` to delete, such as the `/letsencrypt` an earlier
  `certbot_dns_restore` extracted into `/` (old account key and DNS
  credentials). New `tasks/stray.yml` runs after `cleanup.yml`. Each path must
  be absolute and normalized (letters, digits, `.`, `_`, `-`, `/` only) and must
  not be equal to, inside or above the live config dir or
  `/etc/letsencrypt`, `/var/lib/letsencrypt` and `/var/log/letsencrypt`, both as
  given and after resolving symlinks on the host. It must be a real directory
  (not a symlink) with a `renewal/` directory. The live trees must use
  only literal paths: each protected dir is its own real path, the only
  symlinks are certbot's lineage links (`live/<name>/<cert|chain|fullchain|privkey>.pem`
  -> `../../archive/<name>/<same>N.pem`), and every value with a `/` in any
  protected tree's `renewal/*.conf` is an `https://` URL or a plain absolute path
  inside the protected dirs; otherwise nothing is removed. These host checks are
  in `files/certbot_stray_guard.py`, and a read error counts as a refusal. Any
  failed check stops the run before anything is removed; a missing path is
  skipped; check mode only reports. Tests in `tests/test_certbot_dns_rfc2136.py`.

## Unreleased — Grafana password check needs an exact MATCH (2.50.1)

- `graphyard_auth_bootstrap_deploy`: the final Grafana admin password
  verification passed with a wrong password. It tested `'MATCH' in stdout`,
  which is also true for `MISMATCH`. The verification (`until` and
  `failed_when`) and the reset condition now compare the trimmed status line
  exactly (`== "MATCH"` / `== "MISMATCH"`). A new regression test runs the
  embedded check script against a temporary Grafana-style database with the
  right and a wrong password and evaluates the tasks' own conditions. A sweep
  of the collection for the same substring test found no other status token
  that is contained in its opposite.

## Unreleased — Backup archives on the host are owner-only (2.50.0)

- Backup roles no longer leave archives readable by other accounts on the
  host. They wrote them with the default umask (`0644`), e.g.
  `/opt/backups/traefik/*.tar.gz` with `acme.json` inside; only
  `minecraft_java_backup` set `0600`. Every `archive` task now sets
  `mode: "0600"`, and every `tar` either runs under `umask 077` or is followed
  by a task that sets the archive to `0600`: `certbot_dns_backup`,
  `fastdeploy_backup`, `homeassistant_backup`, `homelab_backup`,
  `jellyfin_backup`, `mail_backup`, `mastodon_backup`, `metube_backup`,
  `minio_backup`, `navidrome_backup`, `nyxmon_backup`, `postfixadmin_backup`
  (`templates_c.tar.gz`), `snappymail_backup`, `tailscale_backup`,
  `takahe_backup`, `traefik_backup`, `unifi_backup`, `vaultwarden_backup`
  (also the `.age` file), `wagtail_backup` and `work_app_backup`.
- Archives from earlier runs are fixed by the next backup run: each of those
  roles (and `minecraft_java_backup` and `paperless_backup`) finds the files
  matching `*.tar`, `*.tar.*` and `*.tgz` directly in its backup root and sets
  every one that is not `0600` yet to `0600` with the file module (no
  recursive chmod; a second run changes nothing). Other files stay as they are.
- Backup roots: `homeassistant_backup_dir_mode` and `wagtail_backup_dir_mode`
  default to `0700` (were `0750`), and `homeassistant_backup` now creates its
  backup root explicitly with that mode. `snappymail_backup` gets
  `snappymail_backup_dir_mode` (default `0700`) for its root, which used
  `snappymail_backup_mode`, and `snappymail_backup_mode` (archive and manifest)
  defaults to `0600` (was `0640`). The roots of `fastdeploy_backup`,
  `mail_backup` and `paperless_backup` stay group-traversable because `pg_dump`
  writes into them as `postgres`; there `tar` runs under `umask 077`
  (`fastdeploy_backup`, `mail_backup`) or into a private temporary file
  (`paperless_backup`).
- `fastdeploy_backup` no longer sets the archive to `0644` "for the fetch": it
  applies the new `fastdeploy_backup_archive_mode` (default `0600`) whether or
  not the archive is fetched, and `mail_backup` sets its archive to `0600`
  also when it is not fetched. **Rollout:** the synchronize fetch reads the
  archive as the SSH user; with a non-root SSH user give the archive a group
  of that user and set `fastdeploy_backup_archive_mode` to `0640`.
- `traefik_backup` has a Molecule scenario (an old world-readable archive in a
  `0755` root ends up `0600` in a `0700` root next to a new `0600` archive);
  the `snappymail_backup` scenario checks the root and archive modes;
  `tests/test_backup_archive_modes.py` checks every backup role and runs
  `traefik_backup` on localhost.

## Unreleased — Nyxmon account, removal and restore fixes (2.49.2)

- `nyxmon_deploy`: a fresh host gets the `nyxmon` account the role asks for
  (primary group `nyxmon_group`, `/bin/bash`, `nyxmon_home`). The existence
  check tested `.failed` on a `getent` task with `failed_when: false`, which is
  never true, so the create task was skipped and the "add to group" task
  created the account with useradd's defaults (group `users`, `/bin/sh`).
  Files the service user then created carried group `users`, which the next
  run's recursive ownership tasks would change once. The group task also appended
  `nyxmon` to its own primary group on the run after a fresh install; it now
  runs only for an existing account whose primary group differs.
- `nyxmon_remove`: removes the `sqlite-privacy.conf` drop-ins `nyxmon_deploy`
  installs for `nyxmon` and `nyxmon-monitor`, and their `.service.d`
  directories when they are then empty.
- `nyxmon_restore`: the restored directories (media, static, cache, logs) end
  at `0755` again. `rsync -a` copied the archive directory's `0700`
  (nyxmon_backup creates them that way) onto the live directories, so a
  restore changed their mode and the next deploy changed it back.
- The `nyxmon_deploy` Molecule scenario checks the created account and that
  later runs leave its group alone, and runs `nyxmon_remove` at the end;
  `tests/test_nyxmon_lifecycle.py` pins the task structure.

## Unreleased — Traefik basic-auth hashes stay stable across deploys (2.49.1)

- New shared task file `webapp_deploy_internal/tasks/traefik_basic_auth_hash.yml`
  resolves the bcrypt hash a Traefik basicAuth middleware renders: it reuses
  the hash in the deployed dynamic file while `htpasswd -v` confirms it still
  matches the current password, and hashes anew only when there is no
  deployed hash, the password changed or the hash is malformed. bcrypt salts
  are random, so hashing on every run rewrote the dynamic file on every deploy
  and fired any notified Traefik reload or restart even when nothing changed.
- `traefik_config.yml` uses it, so `fastdeploy_deploy`, `nyxmon_deploy`,
  `chesslab_deploy`, `graphyard_ingress_deploy` and `work_app_deploy` no
  longer rewrite their Traefik file on a no-op deploy. `echoport_deploy`,
  `homelab_deploy`, `jellyfin_deploy`, `metube_deploy`, `minio_deploy`,
  `navidrome_deploy`, `ollama_proxy_deploy`, `open_webui_deploy`,
  `open_webui_venv_deploy` and `weeknotes_home_deploy` switch from their own
  hash tasks to the shared one. That also stops `echoport_deploy`,
  `homelab_deploy` and `minio_deploy` from putting the password into a shell
  command line and `jellyfin_deploy`, `metube_deploy`, `navidrome_deploy`,
  `ollama_proxy_deploy` and `open_webui*_deploy` from passing it as an
  `htpasswd -b` argument: the password reaches htpasswd on stdin only. A
  provided `*_basic_auth_password_hash` is still used as is.
- Check mode: the hash lookup and verification run in check mode too, so a
  `--check` run of an unchanged deploy reports the Traefik file unchanged; a
  pending password change renders a placeholder hash instead of failing on
  the skipped `htpasswd` call (`weeknotes_home_deploy` already did this).
- New Molecule scenario `webapp_deploy_internal/default`: the idempotence step
  fails if a second run rewrites either route, and verify covers a password
  change and a malformed deployed hash. `scripts/checkout-collections-path.sh`
  lets local playbook tests resolve `local.ops_library` roles from the
  checkout.

## Unreleased — FastDeploy runners move to a root-owned directory (2.49.0)

FastDeploy's services root was owned by the `fastdeploy` user, and every
FastDeploy deploy handed the whole site, including the backup scripts that
sudo runs as root, back to it: code running as fastdeploy could rewrite (or,
by renaming a directory, replace) a script and run it as root.

- New role `fastdeploy_runner`: installs a script FastDeploy starts through
  sudo in `/usr/local/libexec/fastdeploy/<service>/` (root:root `0755`
  directories, script root:`deploy` `0750`; fails if a directory above the
  libexec root is not root-owned or is writable by others), writes
  `config.json` with the absolute script path (FastDeploy runs absolute
  `deploy_script` paths as they are; no FastDeploy change needed), writes
  sudoers rules with that fixed path only, runs `commands.py syncservices` as
  the fastdeploy user and then removes the old copy in the services root.
  Idempotent; Molecule covers the migration from the old layout, tamper
  attempts as fastdeploy and deploy, and a run through the sudo chain.
- `echoport_backup` uses it: the runner moves to
  `/usr/local/libexec/fastdeploy/<service>/backup.py`
  (`echoport_backup_libexec_root`). The service sync now runs locally as the
  fastdeploy user; `echoport_backup_api_base`/`echoport_backup_api_token` are
  no longer used.
- `fastdeploy_deploy`: the services root is root:root `0755` and is excluded
  from rsync and from the ownership pass (which replaced the recursive
  `chown` of the whole site); every deploy makes everything below the
  services root root-owned again and creates `fastdeploy_libexec_path`
  (`/usr/local/libexec/fastdeploy`, root:root `0755`).
- `fastdeploy_register_service`: the service directory, the `deploy.py` copy
  and `config.json` are root-owned.
- FastDeploy restores (`fastdeploy_restore`, Echoport `fastdeploy-backup`)
  leave the services root root-owned and restore an archived sudoers file
  only when its scripts are root-owned runners below `/usr/local/libexec`
  (or, for rules that run as `deploy`, in `/home/deploy/runners/`); rules
  naming `/home/fastdeploy/site/services/` are skipped.
- Rollout: deploy FastDeploy, then rerun every backup registration whose
  playbook uses `fastdeploy_runner` (ops-control). Until a registration is
  rerun its script stays in the (now root-owned) services root.

## Unreleased — uv_install works under --check (2.48.2)

- `uv_install`: `ansible-playbook --check` no longer fails. The read-only
  `uv --version` probe ran only in real runs, so check mode reached the version
  parse without a result and failed unless `-e uv_update_existing=false` was
  passed. The probe and the final verification now also run in check mode; a
  pending install or update is reported as one changed task and nothing is
  downloaded or installed. The Molecule scenario covers three `--check` cases.

## Unreleased — archive_deploy documents archive_workers

- `archive_deploy`: the README lists `archive_workers` (default `2`, the
  gunicorn worker count of the web app) under the common overrides. The
  variable already existed; nothing changes for deployments.

## Unreleased — Echoport runner fails closed on a missing mc alias (2.48.1)

- The generic Echoport runner (`echoport_backup`, `backup.py.j2`) checks with
  `mc --json alias list` that the object key's mc alias exists before it
  archives anything and before every `mc cp`/`mc stat`, and fails the backup or
  restore with an error naming the alias and the key prefix. mc reads an
  unknown alias as a local path, so a target without its own alias, whose
  fallback alias had been removed, wrote its archives below the runner's
  working directory and Echoport recorded them as successful backups. The
  alias listing carries the secret key and is never printed.
- New `echoport_backup_minio_require_prefix_alias` (default `false`) refuses
  keys without an entry in `echoport_backup_minio_prefix_aliases` instead of
  falling back to `echoport_backup_minio_alias`.

## Unreleased — Server ad analysis: Delve settings, llama-server role, worker profile runtime (2.48.0)

Slice 16 of the podcast repo's server ad analysis
(`docs/player/specs/server-ad-analysis-design.md`). Nothing changes for a
deployment that leaves the new switches off.

- `delve_deploy`: new `delve_smart_skip_analysis` (default `false`). When on,
  the role installs apt `ffmpeg`, copies the analysis profile JSON
  (`delve_smart_skip_analysis_profile_src`) to `/etc/delve`, creates
  `delve_analysis_media_dir` (delve, 0700; added to the unit's
  `ReadWritePaths` when it is outside the data directory), writes the voxhelm
  producer token and the detector API key to their own files (root:delve
  0640, `no_log`) and renders `DELVE_SMART_SKIP_ANALYSIS`,
  `DELVE_SMART_SKIP_ANALYSIS_PROFILE`, `DELVE_ANALYSIS_MEDIA_DIR`,
  `DELVE_ANALYSIS_MEDIA_DISK_CAP_BYTES`, `DELVE_FFPROBE_PATH`,
  `DELVE_FFMPEG_PATH`, `DELVE_VOXHELM_URL` + `DELVE_VOXHELM_TOKEN_FILE`,
  `DELVE_DETECTOR_URL` + `DELVE_DETECTOR_API_KEY_FILE` and the optional
  timeouts. URLs must be bare origins; a secret must be at least 32 characters
  and not `CHANGEME`, and the detector API key at least 32 of
  `A-Z a-z 0-9 . _ ~ + / = -` (`delve_detector_api_key_pattern`, checked
  without printing it). Off, none of this is
  rendered and the env file and unit are unchanged; the secret files are removed.
  ops-deploy's `delve` service mirrors the new `delve.env.j2` and
  `delve.service.j2` lines byte for byte (its parity tests vendor both).
- New role `llama_server_deploy`: one pinned llama.cpp `llama-server` on macOS
  as a LaunchDaemon, started through a wrapper copied from the control node
  (Delve's `detector-server.sh`, checked to pin the same GGUF SHA-256 and the
  private flags). Installs Homebrew `llama.cpp` when missing (never upgrades)
  and fails unless the installed build is `llama_server_build`; downloads the
  GGUF at a pinned Hugging Face commit with its SHA-256; writes the API key file
  (0600, service user); binds to the host's Tailscale address (`tailnet`) or a
  loopback/tailnet literal; and checks after a start that `/v1/models` serves
  exactly the alias, `/props` the build and one slot, and `/v1/models`
  without the key answers 401. The API key must be at least 32 of
  `A-Z a-z 0-9 . _ ~ + / = -` (`llama_server_api_key_pattern`): llama-server
  skips key-file lines starting with `#` and does not trim, so another value
  could leave it without authentication.
  `llama_server_enabled: false` unloads it and removes the plist and key file.
- `voxhelm_remote_worker_deploy`: new
  `voxhelm_remote_worker_ad_analysis_enabled` (default `false`) for the
  `ad-analysis-v1` profile runtime: installs `whisper-cpp` and `ffmpeg` when
  missing, downloads `ggml-large-v3-turbo.bin` at a pinned commit and checks
  its SHA-256 (or links a verified existing file), renders
  `VOXHELM_WINDOW_MODEL`, `VOXHELM_WINDOW_TIMEOUT_SECONDS` and
  `VOXHELM_FFPROBE_BIN`, and requires Parakeet to be enabled.

## Unreleased

- Remove `stsPreload: true` from all role Traefik templates so their HSTS
  middleware no longer advertises `preload`. No domains were submitted to the
  browser preload list; the owner decided against registration on 2026-10-19.
  HSTS lifetimes, subdomain settings, and all other security headers are unchanged.

## Unreleased — Voice Memo Matter terminology (2.47.1)

- The Voice Memo inbox role's default ASR prompt explains that the owner's
  tracked task term “Matter” can sound like German “Meta”. It asks the model
  to choose from context instead of applying a blanket replacement.

## Unreleased — Mastodon LOCAL_DOMAIN discovery route (2.47.0)

- `mastodon_deploy`: new `mastodon_traefik_local_domain_wellknown` (default
  `false`) for split-domain instances. It renders the Traefik router
  `mastodon-local-wellknown` for
  ``Host(`<mastodon_local_domain>`)`` and the exact paths
  `/.well-known/webfinger`, `/.well-known/host-meta` and
  `/.well-known/nodeinfo`, routed to the Mastodon web service (mastodon-nginx)
  with `mastodon_traefik_local_domain_priority` (default `1000`, above a site
  router's rule-length default) and `mastodon_traefik_local_domain_cert_resolver`
  (empty renders `tls: {}`). Account discovery then no longer depends on the
  site serving `LOCAL_DOMAIN`. `validate.yml` refuses it without Traefik or when
  `mastodon_local_domain` equals the Traefik host.
- With the route on, the federation cache fill (2.46.0) also fills the
  `/.well-known/` entries for `mastodon_local_domain`. A fill entry may now carry
  its own `host`. The list is built in the new
  `tasks/federation_cache_items.yml`.

## Unreleased — Mastodon federation document cache, nginx timing log (2.46.0)

Nothing changes for a deployment that leaves the new switches off, except the
nginx file limit.

- `mastodon_deploy`: new `mastodon_nginx_federation_cache_enabled` (default
  `false`). When on, mastodon-nginx caches the exact paths in
  `mastodon_nginx_federation_cache_locations` (`/actor`,
  `/.well-known/webfinger`, `/.well-known/host-meta`,
  `/.well-known/nodeinfo`, `/nodeinfo/2.0`) in their own zone
  (`mastodon_nginx_federation_cache_path`, `_zone`, `_zone_size`, `_size`,
  `_inactive`, `_lock_timeout`). nginx follows Mastodon's `Cache-Control`,
  replaces `Vary` with a key on normalized `Accept` and the presence of
  `Origin`, collapses concurrent misses (`proxy_cache_lock`, lock timeout and
  age 10 s) and serves the stale entry while it refreshes or while Puma fails.
  After the health check the role fills the cache
  (`mastodon_nginx_federation_cache_prime_hosts`, `_prime`, `_prime_extra`)
  and fails unless a second request is a cache hit. A cached `/actor` keeps a
  federation burst from deadlocking Puma: GoToSocial servers fetch `/actor`
  back to verify Mastodon's signed key fetches while every thread is busy
  with their requests. A purged or evicted entry is cold again until it is
  requested once. Status and account documents are not cached.
- `mastodon_deploy`: new `mastodon_nginx_access_log_timing` (default `false`)
  appends `rt=`, `urt=` and `cache=` to the combined access log format.
- `mastodon_deploy`: the mastodon-nginx unit sets
  `LimitNOFILE={{ mastodon_nginx_limit_nofile }}` (default `65536`). The
  systemd default soft limit of 1024 was below `worker_connections` (4096),
  and nginx warned about it. The next deploy restarts mastodon-nginx.

## Unreleased — MeTube no longer renders DOWNLOAD_MODE (2.44.1)

- `metube_deploy` drops `DOWNLOAD_MODE` from `metube.env` and
  `metube_shared` drops `metube_download_mode`. Upstream MeTube removed the
  setting and ignores it; downloads always run concurrently, and
  `metube_max_concurrent_downloads: 1` gives sequential downloads.

## Unreleased — MeTube builds its pnpm UI before switching sources (2.44.0)

- `metube_deploy` builds the UI with pnpm through corepack (the version in
  `ui/package.json`'s `packageManager`) when `ui/pnpm-lock.yaml` exists, and
  with `npm ci` otherwise. Upstream master moved the UI to pnpm, so `npm ci`
  failed after the new sources were already checked out.
- The UI is built in a staging checkout (`metube_ui_build_dir`, under the new
  shared `metube_ui_build_root: /var/cache/metube`). `metube_install_dir`
  moves to the built commit and gets the new build only after the build
  succeeded; a failed install or build stops the play with the install and
  the running service unchanged. A commit stamp replaces the install marker
  (`metube_install_marker` is gone), and leftover `ui/node_modules`,
  `ui/.angular` and the marker are removed from `metube_install_dir`.
- New `metube_nodejs_min_version` (default `24.15.0`, Angular CLI 22's
  minimum): an older Node.js of the configured major is upgraded, and the role
  fails early if the installed Node.js still does not qualify. The NodeSource
  list `nodesource-metube.list` is now written whole, replacing an older
  major's line instead of keeping it.
- `metube_remove` also deletes `metube_ui_build_root` with the install dir.
- Python dependency tooling is unchanged (`uv sync --frozen --no-dev`).

## Unreleased — Pinned backup SSH key for production and staging (2.43.0)

FastDeploy privilege reduction, stage 1, SSH part.

- New role `echoport_remote_command_guard`: a forced-command allowlist for the
  SSH key the Echoport remote runners use as `root` on production/staging.
  It accepts exactly the commands those runners send (pg_dump/restore of the
  listed databases, `systemctl` for listed units, `scp -f|-t` and
  `rsync --server` inside listed path roots or on the runners' temp dump
  files, the python-podcast private media backup steps), executes them without
  a shell and refuses and logs everything else, including interactive
  sessions and SFTP. The policy is per host and validated by the guard before
  it is installed. Tested against every remote runner's real commands
  (`just test-echoport-remote-command-guard`) and through a real sshd with a
  fish login shell (`just molecule-test echoport_remote_command_guard`).
- `echoport_backup`: the remote runners (homepage/python-podcast production DB
  and staging, marina and villakunterbunt staging) call `scp -O` so the guard
  sees a checkable `scp -f|-t <path>`. heis is unchanged.
- The guard accepts exactly the rsync server commands of the runners' client
  options (download `-a --safe-links`, upload `-a --no-D` with or without
  `--delete`; derived from rsync 3.2.7 and 3.5.0, listed in the role README)
  and refuses everything else (`-L`, `-K`, device/special files, other
  options). The marina and villakunterbunt upload runners pass `--no-D`.
- `scp -t` writes only onto a new path or an existing regular file with one
  link (no symlink, device, FIFO or directory); `scp -f` reads only missing or
  regular files, dump files only when they belong to `postgres`.
- Uploads run unprivileged: `scp -t`, the rsync receiver and `mkdir -p` into a
  path root run as the root's owner (`runuser -u <owner> --`; a root owned by
  `root` is refused), restore dumps are written as `postgres`. The sender can
  no longer create root-owned setuid or device files. The private media tar
  archive (and `scp -f` of it) is only accepted inside a private directory of
  root's (a fresh `mktemp -d`), so a look-alike directory with a planted
  symlink in `/tmp` is refused.
- Django Chat staging DB runner (`django_chat_staging_db_backup.py.j2`) passes
  the guard unchanged: `runuser -u postgres --` forms, `pg_dump` to stdout, the
  runner's three fixed read-only `psql` queries, scratch databases from
  `postgres.scratch_restore_prefixes`, a root-only restore temp dir from
  `temp_dirs`. The guard performs the runner's `umask 077 && cat > <dump>` and
  `pg_restore ... < <dump>` redirections itself, opening the files without
  following symlinks.
- GoToSocial runner (`gotosocial_backup.py.j2`): every remote step is one
  plain command (no `bash -c` script), `scp -O` without `-p`, uploads with
  `--no-D`, and the snapshot is read with `cat` from the service user's temp
  dir, which the guard opens itself without following symlinks. The rollback
  runs the same moves step by step. New policy keys `sqlite_snapshots`,
  `read_files`, `ready_urls`; generic `mv` within one root onto a new name,
  `chmod 0600|0700`, `test -f`.
- `just molecule-test echoport_remote_command_guard` also runs the refused
  rsync options, scp onto a symlink, a SQLite snapshot through the guard and a
  dump upload into a root-only temp dir.
- Accepted risk (documented): restores run `pg_restore` in a PostgreSQL
  superuser session; a crafted dump could run code as `postgres`.
- Rollout: re-run the register playbooks of these runners before pinning a
  host (ops-control `docs/FASTDEPLOY_PRIVILEGES.md`); the new forms also work
  unpinned.

## Unreleased — mailgun-relay Python/Rust implementation switch (2.42.0)

- `mailgun_relay_deploy`: `mailgun_relay_impl` (`python`, the default, or
  `rust`) selects what `mailgun-relay.service` runs. `rust` starts the Rust
  port of the relay (`mailgun-relay` from the GitHub release `rs-v<version>`)
  through the drop-in `/etc/systemd/system/mailgun-relay.service.d/impl.conf`
  (`ExecStart=` override plus `Environment=MALLOC_MMAP_THRESHOLD_=131072`,
  which keeps large attachment buffers from staying resident). New variables
  `mailgun_relay_rust_version`, `_sha256`, `_release_url`, `_local_archive`,
  `_install_root` (`/opt/mailgun-relay`) and `_keep_versions` (3), validated
  before anything changes. With the defaults nothing changes on a host.
- A pinned version is installed with either implementation into
  `<root>/<version>/` (checksum-pinned download or local archive holding
  exactly the regular files `mailgun-relay` and `LICENSE`, an installed
  version never replaced), then validated by the versioned path: `--version` as the
  service user and `--check-config` through `systemd-run` with the unit's
  user, environment file and sandbox. A failure removes a fresh install and
  stops the play for `rust`. For `python` the drop-in is removed before any
  Rust step and a Rust failure is an ignored failure (`WARNING`), so the
  rollback to Python never depends on the release.
- After the health check the role verifies the live process
  (`/proc/<pid>/exe` for Rust, the venv `python -m mailgun_relay` argv for
  Python), records `<root>/.previous-version` when the selection moves, and
  prunes old versions (keeps pinned, live, previous and the newest N).
  Source, venv, env and secrets are still deployed for both implementations;
  existing task and handler names are unchanged.
- Tests: `tests/test_mailgun_relay_deploy.py` covers defaults, release URL,
  validation, task order, the drop-in, failure handling, the live check and
  pruning. First Molecule scenario for the role
  (`just test-mailgun-relay-deploy-molecule`): Python from the public
  repository plus fake release archives built from a small C program that
  answers `--version`, `--check-config` and `GET /health`. It covers
  installing ahead of the switch without a restart, the switch, a version
  change with pruning, a wrong version, a failing `--check-config`, a
  different archive for an installed version and a symlink member (all
  refused with nothing switched), and rollbacks to Python while the pinned
  release fails `--check-config` or its archive is broken.

## Unreleased — Traefik backup includes the dynamic route configs (2.41.0)

- `traefik_backup`: also copies the file-provider directory
  (`traefik_backup_dynamic_dir`, default `/etc/traefik/dynamic`) into the backup,
  so the archive holds `<prefix>-<timestamp>/dynamic/<file>`. Before, a run with the
  defaults archived only `metadata.yml` (`acme.json` is off by default). On by
  default (`traefik_backup_include_dynamic: true`); the run fails when the directory
  is missing. `metadata.yml` records `dynamic_dir` and both include flags.
  `traefik_restore` is unchanged and still restores only `acme.json`.

## Unreleased — graphyard and logyard rsync deploys skip worktree .git (2.40.1)

- `graphyard_deploy`, `logyard_deploy`: the `.git/` entry in
  `graphyard_rsync_excludes` and `logyard_rsync_excludes` is now `.git`, as in
  `mailgun_relay_deploy` since 2.39.1. `.git/` only matched a directory; in a
  git worktree `.git` is a file, and deploys from a worktree copied it to the
  host. rsync does not delete excluded paths on the host, so remove an already
  copied `site/.git` file under `/opt/apps/graphyard` or `/opt/apps/logyard`
  by hand.
- `just test-rsync-git-excludes` (`tests/test_rsync_git_excludes.py`) finds
  every role default exclude list that names `.git` and runs it through
  `rsync --dry-run` against a clone-shaped and a worktree-shaped tree.

## Unreleased — GoToSocial backup counts local statuses on the real schema

- `echoport_backup` (`gotosocial_backup.py.j2`): `verify_snapshot` counted
  `statuses WHERE local = 1`, a column GoToSocial 0.22 does not have, so every
  backup failed. Local statuses are now those whose account has no domain. The
  test fixture uses GoToSocial's columns and includes a remote status.

## Unreleased — Mailgun relay end-to-end probe (2.40.0)

- `mail_monitoring`: optional relay probe (`mail_monitoring_relay_probe_enabled`,
  default `false`). A systemd timer (default every 15 minutes) runs
  `/usr/local/bin/mailgun-relay-probe` as a dedicated system user. It sends
  `POST <url>/v3/<domain>/messages` with Basic-Auth `api:<token>` and one
  message from `mail_monitoring_relay_probe_from` to the monitor mailbox, with
  the subject `<prefix> <UTC time>-<hex>`, and writes `last_status`/`last_run`
  to `/var/lib/<service_name>/state`. The token lives in
  `/etc/<service_name>/token` (probe user, `0600`) and reaches curl on stdin
  only. The script takes `--url` (e.g. another relay instance), `--retries`,
  `--subject-suffix`, `--token-file` and extra curl arguments after `--`.
  Manual runs record nothing unless `--state-file` is given. The role installs
  curl. Disabling the probe again removes the timer, units, script, token and
  state.
- `metrics_endpoint`: new `metrics_endpoint_probe_states` (default `[]`)
  exports probe state files as top-level sections
  (`{"<name>": {"last_status", "last_run", "age_seconds"}}`). A missing or
  malformed file omits the section, so json-metrics rules on it fail. With the
  list empty the rendered script is unchanged.
- `just test-mail-monitoring-probe` also runs the rendered probe against a
  local stub relay (form fields, Basic-Auth, token kept off argv and out of
  the output, state file, exit codes) and the metrics script against probe
  state files. The Molecule scenarios of both roles cover the systemd run and
  the exported section.

## Unreleased — certbot DNS removes the previous provider's credentials

- `certbot_dns_deploy`: new `cleanup.yml`, run after the certificate and
  provider switch. With `certbot_dns_remove_unused_credentials: true` (default)
  it deletes the other provider's credentials file (`certbot_dns_credentials_file`
  for gandi, `certbot_dns_rfc2136_credentials_file` for rfc2136) once no
  `renewal/*.conf` mentions it (symlinked configurations are followed). A
  lineage that still uses it, after a failed switch, in check mode or on
  another lineage, keeps it, and so does any scan error (an unreadable file, no
  configuration at all). Before the scan it drops the previous plugin's
  `dns_<plugin>_*` settings from the managed lineage once that lineage
  authenticates with the configured provider: `certbot reconfigure` leaves them
  behind (certbot ignores them and drops them at the next renewal), and they
  would keep the old file "in use". Tests run the tasks on localhost against a
  temporary config directory.

## Unreleased — Traefik log rotation keeps Traefik writing to fresh files (2.39.2)

- `traefik_deploy`: `/etc/logrotate.d/traefik` now has one block per file.
  `access.log` is renamed, and the postrotate script sends `SIGUSR1` to the
  Traefik main process (`systemctl kill --signal=USR1 --kill-whom=main`)
  instead of running `systemctl reload traefik || true`. The unit has no
  `ExecReload`, so the reload always failed silently and Traefik kept writing
  to the renamed `access.log.1` until its next restart. The fresh `access.log`
  stayed empty, and `notifempty` never rotated it again (macmini: 465 MB in
  `access.log.1`). A failed signal now makes logrotate report an error, and a
  stopped Traefik is not signalled.
- `traefik.log` uses `copytruncate`: Traefik reopens only its access log on
  `SIGUSR1`, never its own log, which it writes with `O_APPEND`.
- The rotation configuration is a template applied by the new standalone
  entry `tasks_from: logrotate`, which the full deploy imports. It writes only
  `/etc/logrotate.d/traefik` and is therefore usable on transaction-managed
  hosts, where the full deploy is refused. The README describes the one-time
  repair for a host that is already stuck on `*.log.1`.
- Tests: `tests/test_traefik_logrotate.py` (`just test-traefik-logrotate`)
  checks both blocks and runs the rendered postrotate script against a stub
  `systemctl`. The Molecule scenario forces a real rotation and checks that
  the unchanged Traefik process holds the fresh `access.log` and `traefik.log`
  open and writes the truncated `traefik.log` from the start.

## Unreleased — mailgun-relay rsync deploys skip rust/ and worktree .git (2.39.1)

- `mailgun_relay_deploy`: `mailgun_relay_rsync_excludes` now excludes
  `/rust/`, the Rust port that lives in the relay repository (sources, plans,
  fixtures and Cargo build output); the Python service needs none of it.
- `mailgun_relay_deploy`: the `.git/` exclude is now `.git`, so it also matches
  the `.git` file of a git worktree, which earlier deploys copied to the host.
  rsync does not delete excluded paths on the host, so remove an already
  copied `/opt/apps/mailgun-relay/site/.git` by hand.
- `just test-mailgun-relay-deploy` runs the default excludes through
  `rsync --dry-run` against a worktree-shaped tree.

## Unreleased — Owner-only fetched backup archives (2.39.0)

- Security: backup roles left the archive they fetch to the controller with
  the controller's umask (usually 0644), although the archives hold
  credentials (`takahe.env`, database dumps, ACME and Tailscale keys, ...).
  `ansible.builtin.fetch` has no `mode` option, so every backup role that
  fetches an archive now follows the fetch with a task that sets the local
  copy to 0600 under the fetch's conditions (also after a `synchronize` pull):
  `certbot_dns_backup`, `fastdeploy_backup`, `homeassistant_backup`,
  `homelab_backup`, `jellyfin_backup`, `mail_backup`, `mastodon_backup`,
  `metube_backup`, `minio_backup`, `navidrome_backup`, `nyxmon_backup`,
  `snappymail_backup`, `tailscale_backup`, `takahe_backup`, `traefik_backup`,
  `unifi_backup`, `vaultwarden_backup`, `wagtail_backup` and
  `work_app_backup` (`paperless_backup` already did this). The task is
  skipped in check mode, where fetch writes nothing (also in
  `paperless_backup`, whose task failed under `--check`). Copies fetched
  earlier keep their mode;
  `find ~/backups -type f -exec chmod 600 {} +` fixes them.
- `fastdeploy_backup`: the `synchronize` pull used `--chmod=ugo=rw`; it now
  uses `--chmod=u=rw,go=` like the other roles.
- `just test-fetched-backup-archive-modes` checks every fetch in
  `roles/*_backup` statically and runs each role's fetch and permission task
  against localhost under umask 022.

## Unreleased — Parakeet for Voxhelm known-speaker jobs (2.38.0)

- `voxhelm_remote_worker_deploy`: new `voxhelm_remote_worker_parakeet_enabled`
  (default `false`). When set, the role installs the `parakeet-mlx` CLI
  (pinned, default 0.5.3) as a uv tool on Python 3.13, downloads
  `config.json` and `model.safetensors` of
  `mlx-community/parakeet-tdt-0.6b-v3` at a pinned commit into a directory
  named after the commit, verifies the weights' sha256 before moving them into
  place, records the commit next to them, and renders the
  `VOXHELM_PARAKEET_*` worker settings. The worker restarts after a CLI
  install. Nothing is installed or rendered while the switch is off.
- `voxhelm_deploy`: new `voxhelm_known_speaker_stt_backend` (default `""`,
  validated to `""` or `"parakeet"`), rendered as
  `VOXHELM_KNOWN_SPEAKER_STT_BACKEND`. `"parakeet"` routes Voxhelm's
  known-speaker jobs to Parakeet with whisper.cpp as the fallback (Voxhelm
  0.1.9 or later).
- The Parakeet tasks that run as the service user use a login shell
  (`become_flags: "-i"`) like the rest of the role; without it the first
  deploy on studio failed in "Check the parakeet-mlx CLI" with
  `getcwd: Permission denied` because the module inherited root's working
  directory.
- `just test-voxhelm-parakeet` covers the env rendering, the validation, the
  install skip and the download/verify order.

## Unreleased — journald retention role (2.37.0)

- Fix `takahe_backup`: `pg_dump` ran as `postgres` and could not write into the
  root-owned 0700 backup directory, so every backup failed at the dump step.
  `takahe_backup_postgres_become_user` now defaults to `takahe_backup_owner`
  (TCP + passfile, as in `mastodon_backup`).
- New `journald_config` role: writes one systemd-journald drop-in
  (`/etc/systemd/journald.conf.d/60-ops-library.conf`) with `Storage=` and the
  size, file-count and age limits (`SystemMaxUse`, `SystemKeepFree`,
  `SystemMaxFileSize`, `SystemMaxFiles`, `MaxRetentionSec`, `MaxFileSec`),
  plus `journald_config_extra_settings` for other `[Journal]` keys. Values are
  validated before anything is written, and the role restarts journald when
  the drop-in changes. `journald_config_state: absent` removes the drop-in
  again.
- The README explains why a host can keep only a day of logs with most of
  `SystemMaxUse` free: journald also rotates when a file's data hash table is
  75% full, every rotation archives the system journal plus each per-UID
  journal, and the default `SystemMaxFiles=100` then deletes the oldest files.
  It shows how to size all three limits from the measured daily volume.
- Molecule scenario `journald_config/default` checks the rendered drop-in,
  `systemd-analyze cat-config`, the rejection of malformed and conflicting
  values, and removal.

## Unreleased — GoToSocial deploy role and Echoport runner (2.36.0)

- New role `gotosocial_deploy`: GoToSocial from a pinned upstream release
  (0.22.2, sha256-verified per architecture), SQLite and local storage in
  `/var/lib/gotosocial`, hardened systemd unit (`ProtectSystem=strict`, one
  writable path, no capabilities), loopback listener on `127.0.0.1:10070`,
  public Traefik route (documented exception to the dual-router policy:
  federation peers cannot do Basic Auth), `/readyz` health check and an admin
  CLI wrapper `/usr/local/sbin/gotosocial-admin`.
- Validation: the host must be the account domain or a subdomain of it
  (GoToSocial refuses to start otherwise), and `gotosocial_extra_config` may
  not carry secrets or any key of `gotosocial_guarded_config_keys` (listener,
  layout, database, storage, registrations).
- The role records `host account-domain` on the first deploy and refuses a
  later deploy with a different pair (GoToSocial cannot change its domain
  layout after federating); `gotosocial_allow_domain_layout_change` overrides
  it for a wiped data directory.
- `gotosocial_traefik_enabled: false` removes the route, so an instance can be
  prepared before a cutover hands it the host name.
- New `echoport_backup/templates/gotosocial_backup.py.j2`: Echoport runner
  for target `gotosocial`, run on macmini against the GoToSocial host over
  SSH. Backup is online: `sqlite3 .backup` as the service user into a private
  temp dir on the host (integrity-checked there and again on macmini), plus the
  media storage, `config.yaml` and the domain-layout marker; `manifest.json`
  (local account/status counts, layout) and `manifest.sha256`; the stored size
  is compared after upload. Restore verifies the recorded checksum, the
  manifest checksums, the database integrity and that the archive's domain
  layout equals the host's, then stops the service, moves the current database
  and storage aside path by path (`*.pre-restore-<ts>`, nothing deleted),
  puts the archived data in place, starts the service and waits for
  `/readyz`. Any failure after the first move swaps back exactly the paths
  that were moved, moves half-restored files and WAL/SHM files the restored
  database created to `*.failed-restore-<ts>`, and leaves the service stopped
  if the previous data cannot be put back. The local archive has a fixed name
  in a private work directory. Host, paths and service are fixed by
  Ansible; key prefixes outside `gotosocial/` are refused.
- Tests: `just test-gotosocial-deploy` (static contracts) and
  `just test-gotosocial-echoport-backup` (runner against a fake host with real
  sqlite3), both part of `just test`; `just test-gotosocial-molecule` (full
  install in a systemd container).

## Unreleased — FastDeploy no longer makes `deploy` root (2.35.0)

FastDeploy privilege reduction, stage 1.

- New role `fastdeploy_legacy_cleanup`: unregisters retired FastDeploy
  services (service and runner directories, then FastDeploy's own service
  sync) and removes listed `/etc/sudoers.d` files, archiving everything into a
  root-only tarball first; idempotent.
- `fastdeploy_register_service` no longer writes
  `deploy ALL=(root) NOPASSWD: ALL` into `/etc/sudoers.d/fastdeploy_<service>`.
  A runner whose playbook needs root must get its own narrow rule.
- `fastdeploy_deploy` no longer installs `/etc/sudoers.d/fastdeploy`
  (`fastdeploy ALL=(deploy) NOPASSWD: <services>/*/deploy.sh *`) and removes
  it when present; every service has its own rule for its script.
- Removed role `apt_upgrade_register`: its only job was to give the FastDeploy
  `deploy` user `ansible-playbook` and `apt` as root. Run upgrades through
  ops-control (`os_apt_maintenance` for the unattended cadence).
- `fastdeploy_restore` and the Echoport FastDeploy runner skip the retired
  entries (`fastdeploy-self`, `apt_upgrade_*`) and their sudoers files when
  restoring older archives (`fastdeploy_restore_retired_entries`,
  `fastdeploy_restore_retired_sudoers`,
  `fastdeploy_echoport_backup_retired_entries`,
  `fastdeploy_echoport_backup_retired_sudoers`). Other archived sudoers files
  are restored only when every rule is the narrow per-script shape the
  registration roles write, so older files with `deploy ALL=(root) NOPASSWD:
  ALL` stay out (`just test-fastdeploy-retired-restore`, Molecule).
- Housekeeping so the gates pass again: a stray merge-conflict line removed
  from this changelog, and the `wagtail_deploy` `tasks/uv_sync.yml` task is
  named `uv_sync | Install dependencies with uv` (strict lint `name[prefix]`).

## Unreleased — Echoport runner for the Django Chat staging database (2.34.1)

- New `echoport_backup/templates/django_chat_staging_db_backup.py.j2`: an
  Echoport runner for the Django Chat PostgreSQL database on the staging host.
  It runs on macmini as the deploy user and reaches the host as root over SSH.
  The backup streams `pg_dump --format=custom` (run as `postgres` there) to
  macmini, checks with `pg_restore --list` that every table in
  `django_chat_staging_db_backup_required_tables` has data, records row counts
  read from the dump, host, server version and checksums in `manifest.json` /
  `manifest.sha256`, uploads one tarball and compares the stored size. A failed
  or empty dump, a missing table or a size mismatch fails the run.
- Its restore never touches the live database: it verifies the archive and the
  dump, copies the dump into a root-only `mktemp -d` directory on the staging
  host (checked by SHA-256, removed afterwards), creates a new scratch database
  `<prefix>_<restore id>` (refusing an existing one), restores into it with
  `--no-owner --no-privileges --exit-on-error` and compares the row counts with
  the manifest. Template variables: `django_chat_staging_db_backup_host`,
  `_remote_user`, `_db_name`, `_postgres_os_user`, `_restore_db_prefix`,
  `_required_tables`, `_counted_tables`, plus the shared `echoport_backup_*`
  MinIO settings (ops-control `register-django-chat-staging-db-backup.yml`).
  Tested by `just test-django-chat-staging-db-backup`.

## Unreleased — DDNS RFC 2136 backend and multi-provider writes

- `dns_deploy` DDNS: new backend `rfc2136` (nsupdate + TSIG against the zone's
  primary, read back with `dig +norecurse`; settings
  `dns_ddns_rfc2136_server`/`_port`/`_key_name`/`_key_algorithm`/
  `_update_zone`, secret `dns_ddns_rfc2136_key_secret` as `DDNS_TSIG_SECRET` in
  `credentials.env`). The secret reaches nsupdate on stdin only and is redacted
  from errors.
- `dns_ddns_providers` writes several providers per run (e.g. Gandi and our own
  BIND while a delegation moves); any provider failing fails the run.
  `status.json` keeps its summary and per-record fields and adds `providers`
  plus `records.*.providers`. Log lines carry the provider name only when more
  than one is configured. Default stays the single `gandi` provider.
- Without `dns_ddns_verify_nameservers`, the public check now asks the NS set of
  the closest enclosing zone that has one, so records in a delegated child zone
  are verified at the child's servers. Tested by `just test-ddns-update`.

## Unreleased — BIND dynamic zones, certbot RFC 2136 provider

- `bind_authoritative_deploy`: zone entries accept `dynamic: true` plus an
  `update_policy` list, rendered as `update-policy { ... };`, so a zone can
  take TSIG-signed RFC 2136 updates. The zone file is a seed: installed once
  (`force: false`) into the new `bind_dynamic_zone_dir` (default
  `/var/lib/bind`, owned by the named user) and never overwritten, because
  named owns the file and its journal afterwards. Validation rejects a dynamic
  zone that is not `master`/`primary` or has no `update_policy`. Existing zone
  lists render unchanged. Tested by `just test-bind-authoritative-dynamic`.
- `certbot_dns_deploy`: new provider `rfc2136` (`python3-certbot-dns-rfc2136`,
  `certbot_dns_rfc2136_server`/`_port`/`_key_name`/`_key_secret`/
  `_key_algorithm`). When an existing lineage was issued with another
  authenticator, the role runs `certbot reconfigure` (dry run against Let's
  Encrypt staging, saved only on success); opt out with
  `certbot_dns_reconfigure_on_provider_change: false`. The credentials and
  RFC 2136 validation tasks are `no_log`. Default provider stays `gandi`.
  rfc2136 credentials go to their own file (`certbot_dns_rfc2136_credentials_file`,
  default `/etc/letsencrypt/dns-rfc2136-credentials.ini`), so the gandi file a
  lineage still references is never rewritten. `certbot_dns_restore` fixes the
  mode of whichever credentials files exist instead of requiring the gandi one.
  Tested by `just test-certbot-dns-rfc2136`.

## Unreleased — DDNS updater fails loudly and has pluggable backends

- `dns_deploy` DDNS: the shell updater is replaced by a stdlib Python updater
  (`/usr/local/bin/ddns-update`, settings in `/etc/ddns/config.json`,
  credentials in `/etc/ddns/credentials.env`). The provider is a backend selected
  by `dns_ddns_provider`; `gandi` is implemented and documented as the pattern for
  further backends.
- Any non-2xx API answer, a read-back mismatch, a failed WAN address detection or
  a missing credential now fails the run with a non-zero exit. Previously a
  Gandi HTTP 403 on every record still ended in `Result=success`.
- Records are read first and written only when they differ; every record is
  logged as unchanged, updated (old -> new) or failed. Credentials are not logged.
- New `dns_ddns_gandi_auth_scheme` (`bearer` for a Personal Access Token, the
  default, or `apikey` for a legacy API key).
- Each run asks the zone's authoritative nameservers for the public view and
  writes `/var/lib/ddns/status.json` (run result, consecutive failures, how long
  the public records have differed from the WAN address). The optional
  `dns_ddns_status_endpoint_*` settings serve it with basic auth for a Nyxmon
  `json-metrics` check.
- The DDNS tasks are tagged `ddns`. `dns_remove` also removes the status endpoint,
  status directory and the legacy script.

## Unreleased — Mastodon sizing guard, emoji purge guard, cross-prefix backup retention (2.34.0)

- `mastodon_deploy`: refuses a `mastodon_db_pool` smaller than
  `mastodon_sidekiq_concurrency` or `mastodon_max_threads` (`DB_POOL` is shared
  by Puma and Sidekiq) and a negative `mastodon_web_concurrency`. The README
  documents the sizing variables; their defaults are unchanged.
- `mastodon_maintenance`: validation moved to `tasks/validate.yml`. The role
  accepts only plain-word
  commands (letters, digits, spaces and `._=/:,+-`; no newlines, quotes or
  shell operators, since commands are rendered unquoted into a shell script),
  and fails when emoji commands are abbreviated (Thor accepts `em pur`) or
  `emoji purge` is not followed only by `--remote-only` /
  `--suspended-only`, because an unscoped purge also deletes local custom emoji
  and tootctl accepts misspelt flags and values such as `--remote-only false`. Command lists
  must be lists, not strings. The README shows profile-media and remote-emoji
  pruning (`media remove --prune-profiles --days N`, `emoji purge --remote-only`).
- `mastodon_backup`: pruning moved to `tasks/prune.yml`. New
  `mastodon_backup_retain_all_prefixes` (default `false`) counts every backup in
  `mastodon_backup_root` against `mastodon_backup_retain`, so one-off backups
  taken under changing prefixes stop accumulating. Default behaviour is
  unchanged. Tested by `just test-mastodon-slim`.

## Unreleased — Wagtail sites deploy without dev dependencies (2.33.0)

- `wagtail_deploy` now runs `uv sync --frozen --no-default-groups`, so a
  deployed site gets its runtime dependencies only. The `dev` group (and any
  other group in `[tool.uv] default-groups`) no longer reaches the host; on
  the first deploy `uv sync` uninstalls those packages from the existing
  venv, which restarts the services. Before, production venvs carried the
  whole dev toolchain (Jupyter, pytest, Sphinx, ...), and packages without a
  wheel for the host's Python, such as PyYAML through Jupyter on 3.15, were
  built from source on every rebuild.
- New `wagtail_uv_sync_groups` (default `[]`) installs named groups with
  `--group`, for a group a site does need on the host. It must be a list.
- New `wagtail_uv_install_default_groups` (default `false`); `true` syncs the
  default groups as before.
- The sync moved into `tasks/uv_sync.yml`; `tests/test_wagtail_uv_sync.py`
  runs it with a real `uv` against local wheels (`just test-wagtail-deploy`).

## Unreleased — Echoport runner for the mail database (2.32.1)

- New `echoport_backup/templates/mail_db_backup.py.j2`: a service-owned
  Echoport runner for the whole `mail` PostgreSQL database (Postfix, Dovecot
  and PostfixAdmin tables). The backup runs `pg_dump --format=custom` as the
  local `postgres` user, checks with `pg_restore --list` that every table in
  `mail_db_echoport_backup_required_tables` has data in the dump, records row
  counts, the server version and checksums in `manifest.json` /
  `manifest.sha256`, uploads one tarball and compares the stored size. A
  failed or empty dump, a missing table or a size mismatch fails the run.
- Its restore never touches the live database: it verifies the archive and
  the dump, creates a new scratch database `<prefix>_<restore id>` (refusing
  an existing one), restores into it with `--no-owner --no-privileges
  --exit-on-error` and compares the row counts with the manifest. Putting the
  data back into `mail` is an attended step (ops-control
  `docs/MAIL_DB_BACKUP_RESTORE_ECHOPORT.md`).
- Template variables (set by ops-control `register-mail-db-backup.yml`):
  `mail_db_echoport_backup_db_name`, `_postgres_os_user`,
  `_restore_db_prefix`, `_required_tables`, `_counted_tables`, plus the
  shared `echoport_backup_*` MinIO settings. Tested by
  `just test-mail-db-echoport-backup`.

## Unreleased — Nyxmon can run the Rust monitoring agent (2.32.0)

- `nyxmon_deploy`: new `nyxmon_agent_impl` (`python`, the default, or
  `rust`) selects which agent `nyxmon-monitor.service` runs. With
  `nyxmon_agent_rust_version` and `nyxmon_agent_rust_sha256` set, the role
  installs that `nyxmon-agent` release from GitHub (checksum-pinned, or
  `nyxmon_agent_rust_local_archive` for development builds) into
  `/opt/nyxmon-agent/<version>/`, with either implementation, so the binary
  can be installed before the switch. The archive must hold only the regular
  files `nyxmon-agent` and `LICENSE` (checked before extraction). An installed version is never modified;
  the same version from a different archive fails the run. Before anything
  points at it, the binary must report the pinned version (`--version`) and
  accept the migrated database (`--check-schema`, as the service user). With
  `rust` the drop-in
  `/etc/systemd/system/nyxmon-monitor.service.d/agent-impl.conf` replaces the
  `ExecStart` with the versioned binary; with `python` it is removed. After the
  restart the role checks the live process (`/proc/<pid>/exe` for Rust, the
  `start-agent` argv for Python) and only then prunes old versions beyond
  `nyxmon_agent_rust_keep_versions` (default 3), keeping the pinned, the
  running and the previously selected version (no pruning with monitoring
  disabled). Rollback is setting `nyxmon_agent_impl: python`
  again; the README documents the emergency rollback on the host.
- Without a pinned version and with `nyxmon_agent_impl: python` the role
  installs nothing and restarts nothing new; it only adds read-only checks
  that the unit runs the venv `start-agent`.

## Unreleased — PostfixAdmin backups fail closed (2.31.48)

- `postfixadmin_backup` no longer publishes a partial backup. `config.local.php`,
  the `admin` table (at least one row) and the `domain_admins` table (no rows
  is fine) are required, and so is the database schema version. A run writes
  into `<timestamp>.tmp/` and renames it only when every required part is
  there; on any failure the `.tmp` directory is removed, the play fails and
  retention does not run. The audit `log` and `templates_c` stay optional:
  a failure is a warning and the part is left out of the manifest.
- The manifest (`manifest_version: 2`) lists exactly the parts written, plus
  `postfixadmin_version`, `db_schema_version` and the skipped optional parts.
  It used to list every part whether or not it existed.
- The `admin` backup keeps every column, and `postfixadmin_restore` restores
  them all, so TOTP secrets, `phone`, `email_other` and tokens survive. Before
  it changes anything, the restore refuses a timestamp that is not a backup
  directory name, a manifest without `contents`, a missing required or listed
  part, a column the target's `admin` table lacks, and a backup from a newer
  schema version than the target's.
- Retention prunes only completed backup directories (`YYYYMMDDTHHMMSS`),
  only after a successful run, and never the newest
  `postfixadmin_backup_keep_min` (new, default 5). Age-only pruning of an
  ad-hoc role could leave just the newest, possibly partial, backup.
- The Echoport runner `echoport_backup/templates/postfixadmin_backup.py.j2`
  gets the same treatment: `admin` (all columns, at least one row) and
  `domain_admins` are required, `log` is optional; `config.local.php`, the
  nginx site and the PHP pool are required, the Traefik config is optional.
  Missing optional parts are reported as warnings. `manifest.json`
  (`format_version: 2`) lists the tables and config files in the archive and
  the schema version. The restore refuses an archive with a missing required
  or listed part, or from a newer schema, before it stops any service;
  archives written before this change still restore. The safety snapshot
  keeps every admin column as well.
- The `postfixadmin_backup` README no longer claims that `mail_backup` covers
  the mail tables; it names the whole-database dumps that do.

## Unreleased — FastDeploy and Nyxmon deploys no longer restart Traefik (2.31.47)

- `fastdeploy_deploy` and `nyxmon_deploy` no longer restart Traefik after
  rendering their dynamic config. FastDeploy restarted it on every run
  (`webapp_deploy_internal_traefik_force_restart: true`), Nyxmon whenever the
  file changed, which was every run because the basic auth bcrypt hash gets a
  new salt each time. Each restart refused or cut every connection through
  that Traefik for 0.5–10 seconds; on macmini on 2026-10-14 repeated deploys
  restarted it 58 times and broke Voxhelm transcript jobs from staging with
  `Connection refused` and `RemoteDisconnected`. Traefik's file provider
  watches `/etc/traefik/dynamic` (`watch = true` in `traefik_deploy`) and
  loads the change without a restart, as `homelab_deploy` already relies on.
  The unused `restart traefik` (FastDeploy) and `reload traefik` (Nyxmon)
  handlers are removed.

## Unreleased — Certbot and mail configuration restores land in /etc again (2.31.46)

- `certbot_dns_restore`: the restore extracted the archive into `/`, but
  `certbot_dns_backup` stores members as `letsencrypt/...`, so it created
  `/letsencrypt` and left `/etc/letsencrypt` unchanged. The role now checks
  every member before anything changes (relative paths below `letsencrypt/`,
  no `..`, symlinks inside the tree, no hardlinks to symlinks), extracts into a staging directory next
  to `/etc/letsencrypt`, keeps the current directory as
  `/etc/letsencrypt.pre-restore-<timestamp>-<suffix>` and moves the restored
  tree into place. The copy is reported and never removed by the role. The
  `certbot_dns_restore_dest` variable is gone.
- `mail_restore` with `mail_restore_config: true` had the same flaw
  (`postfix/...` extracted into `/`). It now validates `config.tar.gz`
  before stopping services and replaces the directories below
  `mail_restore_config_root` (default `/etc`), limited to
  `mail_restore_config_dirs`, keeping pre-restore copies.
- `restore_preserve_internal`: new `replace_from_archive` tasks and the
  `archive_members.py` checker that both roles use.
- Operators: a stray `/letsencrypt` (or `/postfix`, `/dovecot`, ...) left by
  an earlier restore is not removed automatically; check and delete it by
  hand.

## Unreleased — FastDeploy backups never use the shared key `.tar.gz`

- `echoport_backup` (`fastdeploy_backup.py.j2`): the runner builds its object
  key in one place, falls back to `<target>/<timestamp>` when
  `ECHOPORT_KEY_PREFIX` is empty or only slashes, and fails before the upload
  when no prefix can be built. The runner deployed on macmini from 2026-02-11
  until its re-registration on 2026-10-14 predated the committed template: it
  read the Echoport context from the top level of the FastDeploy config file
  instead of `context.env`, so every FastDeploy backup was written to
  `backups/.tar.gz` and nightly retention deleted it. New tests
  (`just test-fastdeploy-backup-key`) pin the nested context lookup and the
  key fallback.

## Unreleased — Stop and verify a hosted Daybook supervisor without hand steps (2.31.45)

- `daybook_operations_runtime_deploy`: new `action: stop` (with `confirmed:
  true`) stops a supervisor running inside the capability host so its code can
  be replaced: it boots out the keeper label, sends SIGTERM to exactly the
  `operations serve` processes found and waits until they, the host's
  `supervisor` session and every store record are gone. It never sends
  SIGKILL, never kills a tmux session and never touches the capability host.
  It refuses with nothing touched without an Aqua session or a running
  capability host, with a stop marker in the store, with a loaded label that
  does not run the keeper, near or inside a run window
  (`daybook_operations_runtime_stop_windows`, checked on the machine's clock
  first and again right before the bootout), or
  when the store or a source named in `daybook_operations_runtime_status_sources`
  still holds work after a bounded wait. A failure after the bootout boots the
  keeper back in on the unchanged code. `daybook_operations_runtime_stop_preflight`
  runs only the read-only checks.
- `daybook_operations_runtime_deploy`: new read-only `action: verify`: label
  loaded, `operations serve` running in the `supervisor` session, the installed
  checkout at the expected revision, no stop marker, and `operations status`
  answering for each named source with the profile enabled.
- `daybook_voice_memo_inbox_deploy`: refuses, before disabling or booting out
  any label, while its label is loaded with the operations keeper or
  supervisor command, or an `operations serve` process runs for the service user. The
  supervisor runs from this install and outlives its keeper, so a deployment
  would otherwise replace its code under it.

## Unreleased — Work app and Homelab restores keep the pre-restore copy (2.31.44)

- `work_app_restore` and `homelab_restore` deleted the
  `<site>.pre-restore-<timestamp>` copy (including `db.sqlite3` and `.env`)
  as soon as a restore passed its health check, which contradicted the
  2.31.36 rule that no restore prunes its pre-restore copies.
  `work_app_restore_safe_snapshot_delete` and
  `homelab_restore_safe_snapshot_delete` now default to `false`; the copy
  stays, for example `/home/work/site.pre-restore-20261014T153000`, and the
  last task reports its path. The owner prunes old copies by hand. Set the
  variable to `true` to get the old delete-after-success behaviour.

## Unreleased — Tailscale auth key off the command line (2.31.43)

- `tailscale_deploy` and `tailscale_restore` ran
  `tailscale up --authkey=<key>` without `no_log`, so the key was visible in
  the host's process list and in Ansible/FastDeploy output on failure or with
  `-v`. Both now use the new `tailscale_shared/tasks/join.yml`: the key is
  written to a private 0600 temporary file, `tailscale up` gets
  `--auth-key=file:<path>` and runs with `no_log`, a failure is reported
  without the key, and the file is removed afterwards. `file:` is supported
  since Tailscale 1.16 and `--auth-key` since 1.22; the role installs the
  latest stable package by default.
- `scripts/check_secret_no_log.py` treats `auth_key`/`authkey` variables as
  secrets, so a key rendered onto a command line is flagged.

## Unreleased — Meaningful idempotence check for the mail relay Molecule scenario (2.31.42)

- `mail_relay_deploy` Molecule scenario: the rewrites-on deployment and its
  checks moved from `converge.yml` into a new `prepare.yml`, and `converge.yml`
  applies only the final configuration (rewrites off; recipient verification,
  postscreen and submission spam discard on). Converge used to apply both
  configurations, so the idempotence step flipped between them and always
  failed. The scenario still covers the rewrites-on state and the switch to
  the final state; the role itself is unchanged.

## Unreleased — Scoped MinIO accounts for media runners, Echoport cleanup and the Daybook bridge (2.31.41)

- `minio_deploy` (`tasks_from: backup_account`): two new switches.
  `minio_backup_account_whole_bucket: true` grants listing and the object
  actions on the whole bucket instead of the prefixes, and
  `minio_backup_account_allow_put: false` drops `s3:PutObject`. Together with
  `minio_backup_account_allow_delete: true` they describe a retention account
  that lists, reads and deletes but never writes, which is what Echoport's
  cleanup needs instead of the MinIO root credentials. The defaults render the
  existing policy documents byte for byte.
- `echoport_deploy`: the cleanup user's mc alias is written with
  `mc alias import` on stdin instead of `mc alias set`, so the credentials no
  longer appear in the host's process list. Its entry leaves
  `scripts/secret_exposure_allowlist.json`.
- `echoport_backup` media runners (`homepage_media_backup.py.j2`,
  `python_podcast_media_backup.py.j2`): the manifest upload runs
  `rclone copyto --no-check-dest`. The key is new on every run, so the skipped
  HEAD probe compared nothing, and the upload stays within what a
  prefix-scoped MinIO account may do. `rclone copy` of the objects still
  compares, so runs stay incremental.
- `daybook_operations_api_backup` (`register_echoport`): the mc alias may
  contain `_`, as the scoped alias `backup-daybook_operations_api` does.

## Unreleased — Graphyard deploys no longer restart Grafana every run (2.31.40)

- `graphyard_auth_bootstrap_deploy`: the Grafana datasource provisioning
  rewrite reports changed only when its status line is exactly `CHANGED`.
  The substring test also matched `UNCHANGED`, so every deploy reported a
  change and restarted the Grafana container (a few seconds of downtime).
  A new regression test runs the embedded script and the task's
  `changed_when` against both outcomes.

## Unreleased — Daybook sessions README describes retired timers (2.31.39)

- `daybook_sessions_deploy` README: a job retired to the Daybook operations
  supervisor writes no launchd log under `/var/log/daybook-sessions/` (its
  status comes from `daybook operations status --binding <source>`), the
  reconcile plist is deleted once retired, and OAuth rotation of a retired unit
  should happen while no `weeknotes` operation runs. Documentation only.

## Unreleased — Python Podcast private media probe works with a fish login shell

- `echoport_backup` (`python_podcast_production_db_backup.py.j2`): the remote
  check whether the private media directory exists runs under `sh -c`. The
  production host's login shell is fish, which cannot parse `if ...; then`,
  so every backup with the private media step failed with "Could not probe".

## Unreleased — Keep task credentials out of arguments and environment (2.31.38)

- Static credential checks now reject secret-looking command arguments and task
  environment values even with `no_log`, including inherited environments (also below a task whose own environment is a template or list). The
  exact baseline records existing out-of-scope findings; focused transport and
  task-behavior regressions run in the test recipes.

- `mail_relay_deploy`: SASL password creation and updates send the password through stdin, keeping it out of command arguments and Ansible task environment values. Existing notifications and change reporting are preserved.

- `redis_install`: The authenticated PING probe reads stdin inside the remote shell and exports REDISCLI_AUTH only to redis-cli, keeping the password out of arguments and task environment values. The probe remains read-only and non-fatal.

- `minecraft_java_backup`: Save coordination reads the RCON password from stdin inside the remote shell and exports MCRCON_PASS only to mcrcon. It never passes the password in command arguments or task environment values; credential input is protected by no_log. Failures report return codes while withholding credential input; the existing save-on condition is preserved.

- `archive_deploy`: Management commands source a rendered 0600 shell environment companion inside the remote shell, keeping credentials out of command arguments and task environment values. The companion uses the same template as the application env file, with shell quoting enabled only for the companion; the existing application/systemd env format is preserved. Command change reporting and check-mode skips are preserved.

- `nyxmon_deploy`: Management commands source a rendered 0600 shell environment companion inside the remote shell, keeping credentials out of command arguments and task environment values. The companion uses the same template as the application env file, with shell quoting enabled only for the companion; the existing application/systemd env format is preserved. Command change reporting and check-mode skips are preserved.

- `fastdeploy_deploy`: Management commands source a rendered 0600 shell environment companion inside the remote shell, keeping credentials out of command arguments and task environment values. The companion uses the same template as the application env file, with shell quoting enabled only for the companion; the existing application/systemd env format is preserved. Command change reporting and check-mode skips are preserved.

- `fastdeploy_self_deploy`: Management commands source a rendered 0600 shell environment companion inside the remote shell, keeping credentials out of command arguments and task environment values. The companion uses the same template as the application env file, with shell quoting enabled only for the companion; the existing application/systemd env format is preserved. Command change reporting and check-mode skips are preserved.

- `fastdeploy_restore`: PostgreSQL CLI tasks use a temporary 0600 passfile owned by the executing database user in a unique 0700 directory, removed in an always block on success or failure. Only the PGPASSFILE path appears in the task environment. Empty passwords retain the existing libpq authentication fallback. Passfile passwords must not contain CR or LF (checked during validation, before the database is dropped); colons and backslashes are escaped. Restore SQL, rollback order and database connection options are unchanged.

- `mastodon_backup`: PostgreSQL CLI tasks use a temporary 0600 passfile owned by the executing database user in a unique 0700 directory, removed in an always block on success or failure. Only the PGPASSFILE path appears in the task environment. Empty passwords retain the existing libpq authentication fallback. Passfile passwords must not contain CR or LF; colons and backslashes are escaped. Restore SQL, rollback order and database connection options are unchanged.

- `takahe_backup`: PostgreSQL CLI tasks use a temporary 0600 passfile owned by the executing database user in a unique 0700 directory, removed in an always block on success or failure. Only the PGPASSFILE path appears in the task environment. Empty passwords retain the existing libpq authentication fallback. Passfile passwords must not contain CR or LF; colons and backslashes are escaped. Restore SQL, rollback order and database connection options are unchanged.

- `paperless_backup`: Document exporter passphrases now use stdin, with no stdin read for an empty passphrase; the obsolete exporter-environment fact is removed. PostgreSQL CLI tasks use a temporary 0600 passfile owned by the executing database user in a unique 0700 directory, removed in an always block on success or failure. Only the PGPASSFILE path appears in the task environment. Empty passwords retain the existing libpq authentication fallback. Passfile passwords must not contain CR or LF; colons and backslashes are escaped. Restore SQL, rollback order and database connection options are unchanged.

- `mastodon_restore`: PostgreSQL CLI tasks use a temporary 0600 passfile owned by the executing database user in a unique 0700 directory, removed in an always block on success or failure. Only the PGPASSFILE path appears in the task environment. Empty passwords retain the existing libpq authentication fallback. Passfile passwords must not contain CR or LF; colons and backslashes are escaped. Restore SQL, rollback order and database connection options are unchanged.

- `takahe_restore`: PostgreSQL CLI tasks use a temporary 0600 passfile owned by the executing database user in a unique 0700 directory, removed in an always block on success or failure. Only the PGPASSFILE path appears in the task environment. Empty passwords retain the existing libpq authentication fallback. Passfile passwords must not contain CR or LF; colons and backslashes are escaped. Restore SQL, rollback order and database connection options are unchanged.

- `wagtail_restore`: the live-database safety dump, the SQL restore and the rollback from the safety dump read the password from a private 0600 passfile (0700 temporary directory, removed in the restore's always section) instead of `PGPASSWORD` in the task environment. Passwords with CR or LF are rejected before services stop.

- `paperless_restore`: Document importer passphrases now use stdin, with no stdin read for an empty passphrase. PostgreSQL CLI tasks use a temporary 0600 passfile owned by the executing database user in a unique 0700 directory, removed in an always block on success or failure. Only the PGPASSFILE path appears in the task environment. Empty passwords retain the existing libpq authentication fallback. Passfile passwords must not contain CR or LF; colons and backslashes are escaped. Restore SQL, rollback order and database connection options are unchanged.

- `unifi_deploy`: MongoDB user creation JSON-quotes credentials and database names and executes with --file, preserving literal quotes/backslashes and reporting script failures through the existing recovery path. Authenticated mongosh tasks read credentials from a 0600 JavaScript file in a unique private temporary directory, run with --file, and remove the directory in always on success or failure. Home Assistant password hashing reads its inputs through stdin. Existing retries, user-management recovery and removal toggles are preserved.

- `unifi_remove`: Authenticated mongosh tasks read credentials from a 0600 JavaScript file in a unique private temporary directory, run with --file, and remove the directory in always on success or failure. Existing retries, user-management recovery and removal toggles are preserved.

- `unifi_restore`: protect MongoDB verification results with conditional no_log and mark existing aggregate password arguments for a live restore/rollback rehearsal before conversion.

- `minio_restore`: mark existing aggregate MC_HOST credential environments for a live service restore rehearsal before conversion.

## Unreleased — Pin and verify privileged release downloads (2.31.37)

- `echoport_backup`: pin and verify mc using the existing MinIO installer tasks. Reconcile the installed binary on every deploy, using the project’s GitHub release after dl.min.io was discontinued. A differing mc binary is replaced at the next deploy.
- `sops_dependencies`: verify the pinned Linux amd64 sops and age downloads using published SHA-256 values (sops checksum file; age's signed GitHub build attestation), including the sops apt fallback.
- `uv_install`: replace the root-run shell installer and automatic self-update with pinned, SHA-256-verified uv/uvx archives for Linux and macOS on x86_64/ARM64. Bump version and checksums together. Reject `uv_version: latest`; pin the three consumer-role defaults to the verified version. Both older and newer installed versions are replaced when updates are enabled; extraction supports GNU and BSD tar.
- `shell_basics_deploy`: replace the root-run chezmoi installer and release lookup with a pinned, verified Linux amd64/arm64 archive. Correct the alternatives module namespace and clean temporary archives after failures. Reject `shell_basics_chezmoi_version: latest` and replace both older and newer differing versions with the pin.
- `vibe_coding_deploy`: verify pinned lazygit, Neovim and zellij release archives and rustup-init binaries on Linux x86_64/ARM64. The extracted zellij binary is also checked against the project's published `.sha256sum` before it is copied into place. Neovim v0.12.5 publishes no checksum file: its pin is the GitHub release asset digest (via the releases API), not a project checksum. Keep existing installation guards and paths. The NodeSource signing-key download is unchanged: no vendor-published checksum was found. Add `just test-root-downloads` to the default test and strict lint gates to reject new unchecked downloads in these five roles; only that exact existing signing-key URL is exempt.

## Unreleased — Restore roles retain every pre-restore copy (2.31.36)

- Jellyfin, Navidrome, MeTube, Minecraft Java, SnappyMail and Wagtail use one
  internal preservation task file. Directory replacements rename live state to
  a unique timestamped sibling; mount points use a space-checked independent
  copy verified before emptying live contents. Nested mounts fail closed.
  Service stops fail closed (an absent Minecraft unit still permits restore
  before deploy). SnappyMail now quiesces nginx/PHP-FPM and restarts them only
  after success or a failure before live changes; restart errors are fatal.
  Its staging stays beside the data and is removed even on failure.
  No restore prunes these copies. Final reports show paths and sizes; each role
  README gives the exact manual cleanup pattern. SnappyMail extracts archives
  into staging before replacing data.
- Wagtail validates compressed SQL before stopping services, verifies a retained
  live database dump before dropping the database, restores SQL in one
  transaction and recovers from the safety dump if SQL replacement fails,
  leaving services stopped when service management is enabled. Failures after
  SQL commits keep the restored database. Nonempty legacy
  `wagtail_restore_postgres_target_opts` overrides now fail validation explicitly.
  Its site copy and database dump remain available for manual recovery.
- `snappymail_restore` Molecule scenario: after the first restore it restores
  twice more over live data and checks that each run leaves one more
  `.pre-restore-*` copy holding the replaced data, then that a mount-point live
  directory whose copy does not fit its parent filesystem fails at preflight
  with the live data unchanged and no copy created.

## Unreleased — FastDeploy runner step states (2.31.35)

- `fastdeploy_register_service`: advisory systemd verification now reports `success` with a
  `WARNING:` message containing the unit name and systemd state when the unit is inactive.
  The former `warning` state was rejected by FastDeploy's API with HTTP 422. Regression tests
  audit step-state literals across the runner templates and helpers and exercise rendered
  verification paths; only `running`, `success`, and `failure` are emitted.
- `fastdeploy_register_service` Molecule scenario: the mock `secrets/prod/*.yml`
  fixtures it seeds are now committed (the repository's `secrets/` ignore rule had
  kept them out), so the scenario runs from a fresh clone.

## Unreleased — Per-target MinIO backup accounts, mc aliases without credentials on the command line (2.31.34)

- `minio_deploy`: new entry point `tasks_from: backup_account`. It creates or
  updates one MinIO user per backup target whose policy `backup-<name>` allows
  reading, writing and listing only `<bucket>/<prefix>/` (no delete unless
  `minio_backup_account_allow_delete` is set, no admin API). The secret reaches
  `mc admin user add` on stdin, and the run proves that the user holds exactly
  that policy. See the role README, "Backup accounts".
- `echoport_backup`: the mc alias is now imported with `mc alias import` from
  stdin instead of `mc alias set <alias> <url> <key> <secret>`, which showed
  the credentials in the host's process list while the task ran. It is
  imported only when the stored values differ. The tasks are also an entry
  point for other plays (`tasks_from: minio_alias`), take a list of OS users
  (`echoport_backup_minio_alias_users`) and remove the aliases named in
  `echoport_backup_minio_retired_aliases`.
- `echoport_backup`: the generic runner can use one mc alias per target
  (`echoport_backup_minio_prefix_aliases`, by first segment of the object
  key). The default, an empty mapping, keeps the single alias.

## Unreleased — Voxhelm prune job can run once a day at a fixed time (2.31.33)

- `voxhelm_deploy`: new `voxhelm_prune_daily_time` (default `""`). Set to a
  quoted `"HH:MM"` (host local time), the `de.wersdoerfer.voxhelm-prune`
  launchd job runs `prune_job_artifacts` once a day at that time
  (`StartCalendarInterval`) instead of every `voxhelm_prune_interval_seconds`
  (`StartInterval`, still the default). The role rejects anything but `00:00`
  to `23:59`, including the number YAML makes of an unquoted `14:30`. Nothing
  changes for hosts that leave it empty; the job stays off and in dry-run mode
  by default.

## Unreleased — New `nodejs_install` role (2.31.32)

- New bootstrap role `nodejs_install`: installs one Node.js release line
  (`nodejs_install_major`, default `24`) system-wide from the NodeSource apt
  repository, pins the `nodejs` package to that origin and fails unless
  `/usr/bin/node` reports that major version. On a
  host that has the distribution's Node.js it replaces `nodejs` and removes the
  distribution's separate `npm` package (NodeSource bundles npm) together with
  the packages that depend on it; runtimes with their own Node.js, such as the
  nvm one of `mastodon_deploy`, are not touched. The role README lists what
  changes on the host and how to go back. A Molecule scenario converges from
  Ubuntu 24.04 with Node.js 18 and `npm` to Node.js 24.

## Unreleased — Nyxmon restore probe works with HTTPS-enforcing settings (2.31.31)

- `nyxmon_restore`: the post-restore HTTP probe of
  `http://127.0.0.1:10017/admin/login/` now sends `X-Forwarded-Proto: https`
  by default (`nyxmon_restore_health_headers`). With
  `config.settings.production`, the `nyxmon_deploy` default, Nyxmon answers a
  plain-HTTP request with a 301 to HTTPS, which the probe followed to a TLS
  port that does not exist and then failed the restore. Nyxmon's
  `config.wsgi_proxy` entrypoint trusts the header from loopback, so the probe
  is answered like a request that came through Traefik. Settings modules
  without an SSL redirect ignore the header. Nyxmon no longer ships
  `config.settings.macos`; do not set `nyxmon_django_settings_module` to it.

## Unreleased — Daybook sessions and Photos offload deploy again on a root connection (2.31.30)

- `daybook_sessions_deploy`: the environment probe, the removal of a broken
  environment and the pinned-Python check now switch to the service user with a
  login shell (`become_flags: "-i"`), like every other task of the role. On a
  host reached as root they started in root's working directory, which the
  service user cannot read: the probe's module died in `getcwd`, the role read
  that as an interpreter that cannot start, and the removal failed the same
  way, after the checkout had already moved and before `uv sync` and the
  wrappers. Hosts reached as the service user were not affected. A static test
  requires the login switch on every task that becomes the service user.
- `daybook_photos_offload_deploy`: the pre-sync probe now asks whether the
  existing environment runs exactly the pinned uv-managed Python, not only
  whether its interpreter starts. `uv sync` replaces an environment on another
  Python by unlinking its directory, which the service user cannot do inside
  the root-owned checkout (`failed to remove directory …/.venv: Permission
  denied`); root now removes and recreates the directory in that case as it
  already did for a dead interpreter, and uv fills the empty directory. A
  directory a failed run left empty is synced in place.

## Unreleased — NyxBoard login can be required by the deploy role (2.31.29)

- `nyxmon_deploy`: new `nyxmon_require_login` (default `false`), rendered as
  `NYXBOARD_REQUIRE_LOGIN` into the shared `.env`. Set to `true`, every
  NyxBoard page requires a logged-in Django user, inside the unchanged Traefik
  dual router; the Django admin login and plain loopback `GET` probes are
  unaffected. The role does not create an account: create one on the host
  first, and deploy a Nyxmon version whose selected settings module marks the
  session and CSRF cookies `Secure`. The default renders `false`, so existing
  deployments behave as before. Render tests and the Molecule verify cover the
  default and the rendered boolean.

## Unreleased — PostfixAdmin schema setup is idempotent again (2.31.28)

- `postfixadmin_deploy`: schema setup recognises both legacy and current
  `upgrade.php` messages for an up-to-date database, avoiding false changes
  during repeated deployments while still reporting applied updates as changed.
  Render/static regression coverage checks both messages and real update output.

## Unreleased — Daybook sessions checkout can follow a branch head (2.31.27)

- `daybook_sessions_deploy`: no-fetch mode (`daybook_sessions_repo_update:
  false`) accepts `daybook_sessions_repo_bundle_src`, a controller-side git
  bundle carrying `daybook_sessions_repo_ref`. When the dedicated checkout lacks
  that commit, the role copies the bundle next to it (service-user-owned, mode
  0600), requires it to carry the commit at a ref below `refs/`, fetches its refs into
  `refs/bundle/*` and removes the copy; the existing ownership, cleanliness and
  local detached-checkout steps then run unchanged. A checkout that already
  holds the commit copies nothing. Private control can so install a branch head
  it resolved to a commit at deploy time on a host without a repository
  credential, instead of a commit staged there by hand. Empty (the default)
  keeps the previous behaviour.
- `daybook_sessions_deploy`: the root-owned weeknotes activation proof names
  the Daybook commit under which the identity migration was applied. An
  ordinary deployment required that commit to equal the one being installed, so
  the checkout could never move without a new attended apply. It now requires
  the proof's commit to be the installed one or an ancestor of it
  (`git merge-base --is-ancestor`); the plan hash, file ownership and modes,
  and the re-verification of the attestation by the installed Daybook are
  bound exactly as before, and a checkout moved backwards or onto unrelated
  history is refused. The operator rail and the activation task still require
  and write the exact installed commit, so each verified apply moves that
  anchor to the commit installed then.

## Unreleased — Explicit proxy trust, quieter credential queries, private temp paths and opt-in unit hardening (2.31.26)

- `fastdeploy_deploy` explicitly trusts proxy headers only from `fastdeploy_forwarded_allow_ips`
  (default `["127.0.0.1"]`); configure trusted proxy addresses for login throttling.
  The separate `fastdeploy_self_deploy` units still use implicit Uvicorn defaults.
- PostfixAdmin admin queries and backup writes suppress password hashes in task logs;
  the credential checker now covers password-bearing PostgreSQL queries,
  including existing mail provisioning and admin restore tasks.
- UniFi/Home Assistant no longer generate passwords in controller `/tmp` files.
  Supply the existing password via inventory/SOPS or the supported remote password file.
- Minecraft mcrcon builds and UniFi MongoDB scripts use unique remote temporary
  paths with cleanup on success and failure.
- Marina, Takahe, MeTube, Navidrome and Open WebUI venv provide opt-in systemd
  hardening, disabled by default; validate on a host before enabling.
- Removed a stray merge marker between the 2.31.18 and 2.31.17 notes;
  regression checks reject conflict markers in tracked text files.

## Unreleased — Preserve OpenClaw proxy attribution across restarts (2.31.25)

- `openclaw_deploy` supports opt-in `openclaw_network_mode: host`, forcing a
  loopback-only Gateway listener and using the host port directly. This
  preserves direct-local API access alongside host-side Traefik proxy
  attribution under 10.2; bridge networking remains the default.
  Opting in shares host networking with agent tools and skills, making
  host-loopback services reachable and auxiliary listeners use host ports.
  The Compose CLI follows the selected mode. Managed `gateway.port` now comes
  from the host or container port variable, including existing configs. A
  separate 300-second `openclaw_startup_timeout` controls TCP port waiting;
  in host mode it allows entrypoint Doctor/bootstrap before the listener
  opens. Bridge mode still probes the published port, followed by the
  existing authoritative CLI/channel readiness checks.

- `openclaw_deploy` stops its Compose stack with `stop` instead of `down`,
  retaining the bridge gateway address across service restarts and image
  upgrades. Host-side reverse proxies can trust their actual single bridge
  gateway IP without a broad container-subnet allowlist. OpenClaw 10.2 rejects
  proxy-shaped requests with missing trusted attribution. Explicit removal
  still tears down the network through `openclaw_remove`.
- Plugin and audio SecretRef CLI containers share the matching running
  gateway's PID namespace, respecting its state ownership while retaining
  host networking and fresh environment-file values. Offline activation uses
  one-shot containers without PID sharing. A mismatched live
  image fails closed; this fixes same-version 10.2 reconciliation refusing
  otherwise valid plugin inspection and attempting an unnecessary install.

## Unreleased — OpenClaw 2026.10.2 upgrade guidance

- `openclaw_deploy` README examples now use `v2026.10.2` and document its matching
  official Codex plugin, stopped-gateway backup and activation checks. The
  existing Doctor activation workflow remains the deployment path.

## Unreleased — Paperless backup archive is owner-only (2.31.24)

- `paperless_backup` no longer leaves the finished archive world-readable. The
  role set it to mode `0644` "for the fetch" in the `0755` backup root, so
  every account on the host could read all documents, the database dump and
  the service configuration with its secrets. tar now writes into a fresh
  `0600` temporary file that is renamed into place, so the archive is
  owner-only from its creation (also when it replaces an existing file); the role then applies
  `paperless_backup_archive_mode` (new, default `0600`) and
  `paperless_backup_owner`, whether or not the archive is fetched. The local
  copy stays in the `0700` local directory and is set to `0600` after the
  fetch (both fetch methods). **Rollout:** the fetch reads the archive as the SSH user;
  with a non-root SSH user set `paperless_backup_group` to a group of that user
  and the mode to `0640`. Archives from earlier runs keep mode `0644`: run
  `chmod 600 /opt/backups/paperless/*.tar.*` once on the host.
- `paperless_deploy` adds `paperless_bind_address` (default `0.0.0.0`, the
  value that was hard-coded for gunicorn in the unit and in
  `gunicorn.conf.py`). The role's Traefik route and health check already use
  `127.0.0.1`; set the variable to `127.0.0.1` to stop serving plain HTTP on
  the LAN and tailnet addresses. Nothing changes until it is set.

## Unreleased — Optional source restriction for the UniFi controller route (2.31.23)

- `unifi_deploy` adds `unifi_traefik_ip_allowlist` (default `[]`). The role
  publishes the controller admin UI as `unifi.<domain>` with a `Host()` rule
  only: no Basic Auth and no source restriction, so the controller's own login
  is all that stands between the internet and the network configuration. With
  a list of IP addresses or CIDR ranges the router gets an `ipAllowList`
  middleware and other clients receive 403. The empty default renders the same
  file as before, byte for byte, so nothing changes until the variable is set.
  A value that is not a list of parseable networks (a bare string, a name, an
  empty entry, `192.168.1.0/33`, `999.999.999.999`) is refused during
  validation, before the role changes anything; Traefik would otherwise drop
  the route.
  Device adoption (port 8080) does not go through Traefik and is unaffected.

## Unreleased — Frozen application lockfiles and owner-only FastDeploy .env (2.31.22)

- Echoport and Nyxmon source-pyproject deployments preserve and install from the
  committed `uv.lock` with `uv sync --frozen`. Rsync validates and copies the
  lockfile separately, notifying restart handlers only when inputs change.
  Missing source lockfiles now fail deployment. Nyxmon's generated PyPI project
  retains dependency resolution without deleting its host-generated lockfile.
- FastDeploy deploy and restore now write the application `.env` with the documented owner-only mode `0600`;
  its service and helpers do not require group read access.

## Unreleased — FastDeploy rollout check without python-jose (2.31.21)

- `fastdeploy_deploy` failed at its last step ("Mint FastDeploy validation
  token") against a FastDeploy that uses PyJWT: the role imported `jose`, which
  the application no longer installs. The token is now minted by FastDeploy's
  own `deploy.auth.create_access_token`, run with the application's interpreter
  (`files/mint_validation_token.py`). It signs with the `SECRET_KEY` and
  algorithm from the site's `.env`, so the role no longer depends on the JWT
  library and no longer puts the secret key on a `python -c` command line. The
  user name and lifetime go in on stdin.
- A failed mint is reported with its exit code and the last line of the error
  output instead of only "output has been hidden".
- `tests/test_daybook_operations_service_token.py` still refuses
  `create_access_token` in every role, with this one user-token helper as the
  named exception: service tokens keep going through `issueservicetoken`.
- `fastdeploy_rollout_validation_token_algorithm` is gone; the algorithm is the
  one FastDeploy is configured with. A playbook that still sets it is unaffected.
- New `fastdeploy_legacy_token_users` (default `[]`, nothing happens): a
  temporary bridge for the legacy service token grace period. FastDeploy
  accepts a service token only while the user named in its `user` claim
  exists, also inside `LEGACY_SERVICE_TOKENS_ACCEPTED_UNTIL`. The listed names
  are created with FastDeploy's `commands.py createuser` and the hash of a
  random password that is generated on the host and discarded, so there is no
  password login. See "Legacy token users" in the role README for what such a
  user can do and how to remove it after the tokens are rotated.

## Unreleased — Edge frame options match the backends (2.31.20)

- The Traefik headers middleware of `archive_deploy`, `chesslab_deploy`,
  `echoport_deploy`, `homelab_deploy`, `minio_deploy` (console),
  `navidrome_deploy`, `nyxmon_deploy`, `weeknotes_home_deploy`,
  `work_app_deploy` and the Grafana router of `graphyard_ingress_deploy` now
  sets `X-Frame-Options: DENY` instead of `SAMEORIGIN`. Each of these backends
  answers `DENY` itself and Traefik replaces the backend's value, so the edge
  had been weakening it. None of them frames its own pages. Takes effect with
  each service's next deploy.
- `SAMEORIGIN` stays where the backend sends `SAMEORIGIN` or no header
  (fastdeploy, homeassistant, jellyfin, metube, ollama-proxy, open-webui,
  opsgate, static-site, vaultwarden) and for `wagtail_deploy`, whose admin
  previews pages in same-origin frames. `takahe_deploy` is unchanged until what
  the deployed Takahe sends has been checked.
- `tests/test_traefik_frame_options.py` records the value and the reason for
  every headers middleware; a template that adds or changes one fails until the
  table is updated.

## Unreleased — Deploy secrets off command lines (2.31.19)

- `archive_deploy` passes the admin password to `manage.py ensure_admin_user`
  on standard input (`--password-stdin`) with `no_log: true` instead of
  `--password` on the command line, where Ansible printed it in every failure
  result and `ps` showed it. A follow-up task reports a failure with the
  return code and stderr. The task reports "changed" only when the user was
  created or the password changed. **Rollout:** needs an archive checkout
  whose `ensure_admin_user` supports `--password-stdin` (archive main since
  2026-10).
- `minecraft_java_deploy` runs its RCON test with `no_log: true` and feeds the
  password on stdin to a shell wrapper that exports `MCRCON_PASS` for mcrcon,
  instead of `mcrcon -p <password>` in a shell command. A task-level
  `environment:` is not used, because Ansible puts it on the remote shell's
  command line.
- `metrics_endpoint` sets `no_log: true` on the two `htpasswd` tasks that read
  the password from stdin (module arguments are printed with `-vvv`).
- `scripts/check_secret_no_log.py` (`just test-secret-no-log`, part of
  `just lint-strict`) now also fails on `command`/`shell`/`raw` tasks that
  render a secret-named variable into the command line or `stdin` without
  `no_log: true`. Nothing is baselined.

## Unreleased — Time synchronization check (2.31.19)

- Add `time_sync_check`: a read-only role that verifies a systemd host's clock
  is synchronized. It checks that chrony or systemd-timesyncd is active, that
  the kernel reports `NTPSynchronized=yes`, that the measured offset is under
  `time_sync_check_max_offset_seconds` (default 1 s), and that the host clock is
  within `time_sync_check_controller_max_skew_seconds` (default 30 s) of the
  controller clock. It fails with the list of problems, or warns and continues
  with `time_sync_check_fail: false`. It never changes time settings and always
  reports `changed=0`. The collection has no host baseline of its own, so
  include the role from the baseline or preflight play that calls the
  collection; `files/time_sync_status.py` also runs standalone for monitoring.

## Unreleased — Nyxmon deploys without spurious restarts (2.31.19)

- `nyxmon_deploy` (rsync method) no longer requests a restart on every run.
  The Django source sync ran with `delete: true` and removed the `venv` symlink,
  `uv.lock`, `pyproject.toml` and the extra files (`README.md`) that the role
  writes into the site root after it. The sync, the two copy tasks and the uv
  install (which rebuilds the project when `pyproject.toml` gets a new mtime)
  therefore all reported "changed", and every deploy restarted nyxmon and
  nyxmon-monitor. The sync now excludes those role-managed paths, anchored to
  the site root, and both syncs pass `--omit-dir-times`, the same pattern as
  the roles fixed in 2.31.16. Real changes still notify both restart handlers.
  Tasks that do not notify a restart can still report "changed" (the role
  removes `uv.lock` before each `uv sync`, which recreates it).

## Unreleased — Delve health check after restart (2.31.19)

- `delve_deploy` flushes its handlers before the `/health` check. A changed
  binary, env file, StoreKit bundle or unit now restarts delve first, and the
  check then waits for the new process. Before, the check passed against the
  old process and the restart fired at the end of the play, into the caller's
  smoke test (502 through Traefik).

## Unreleased — Voxhelm worker private URL hosts and edge frame options (2.31.18)

- `voxhelm_remote_worker_deploy` adds `voxhelm_remote_worker_private_url_hosts`
  (default `[]`), rendered as `VOXHELM_PRIVATE_URL_HOSTS` in the worker env file
  only when set. Workers re-validate claim input with the same redirect and
  private-address checks as the control plane, so a worker without the control
  plane's `voxhelm_private_url_hosts` refuses jobs whose source resolves to a
  private address. Validation accepts the same host names as `voxhelm_deploy`.
- `voxhelm_ingress_deploy` now sets `X-Frame-Options: DENY` at the edge instead
  of `SAMEORIGIN`. Traefik's headers middleware replaces the backend's value, so
  the edge had been weakening the `DENY` Voxhelm sends itself. Takes effect on
  the next Voxhelm ingress deploy.

## Unreleased — Daybook Paperless scan intake adapter (2.31.17)

- `daybook_operations_runtime_deploy` accepts the `paperless.intake.v1` kind
  (Daybook's Paperless scan intake, on Atlas), so a profile that names it is
  not refused. Nothing runs until ops-control declares the kind and the server
  has an enabled source for it.

## Unreleased — Application code change restarts (2.31.16)

- `homelab_deploy` and `nyxmon_deploy` now notify restart handlers when source
  code, dependency inputs, or installed dependencies change. Nyxmon restarts both
  its web and enabled monitoring units; uv change detection includes stderr and
  package removals. Existing restart-on-change settings remain respected.
- `echoport_deploy`, `takahe_deploy`, `heis_deploy` and `marina_deploy` now
  restart their services when synced source, the virtualenv or installed
  dependencies change; Takahe restarts both gunicorn and stator.
- `otbr_deploy` restarts otbr-agent (and otbr-web when enabled) after a rebuild.
- `graphyard_deploy`, `mailgun_relay_deploy`, `wagtail_deploy`,
  `weeknotes_home_deploy`, `archive_deploy`, `chesslab_deploy` and
  `open_webui_venv_deploy` detect uv dependency changes from stderr (where uv
  reports them) including removals, and restart on virtualenv creation;
  Graphyard now restarts web and agent after dependency changes.
- Controller-push rsync tasks in these roles no longer copy controller
  ownership, so the later ownership fix-up does not make every sync report a
  change and restart the service unconditionally. Takahe also stops copying
  controller modes over its 0750 site directories, Echoport's deleting sync
  keeps role-managed site files (`.env`, `venv`, `uv.lock`, the separately
  copied `pyproject.toml` and extra files, the staging helper and SQLite
  WAL/SHM files), and Wagtail's deleting sync keeps its `venv` symlink.
  These syncs also pass `--omit-dir-times`, so directory mtime bumps from
  role-side writes (such as the regenerated `uv.lock`) are not source changes.

## Unreleased — Monitoring delivery probes (2.31.15)

- `mail_spam_deploy` adds an optional original-source-IP, sender, recipient and
  subject scoped exemption from spam actions. Scanning/logging continues;
  `{}` disables the exemption. The role manages `local.d/settings.conf`.

## Unreleased — OpenClaw reasoning default (2.31.14)

- `openclaw_deploy` optionally manages `agents.defaults.thinkingDefault` with
  `openclaw_agent_thinking_default`; empty preserves the runtime setting.
- Add the configured primary to an existing non-empty model allowlist while
  preserving model entries and parameters. Configs without an allowlist remain
  unrestricted.

## Unreleased — Docker build cache maintenance

- Add `docker_cache_cleanup`: a configurable daily systemd timer for age-filtered
  build cache cleanup, preserving images, containers and volumes.

## Unreleased — Paperless search index recovery (2.31.13)

- `paperless_deploy` rebuilds the full search index after migrations on every
  deploy, briefly pausing all configured Paperless services. This repairs empty indexes
  whose schema sentinels already look current after an upstream schema change.
  Previously running services resume on failure, but deployment fails until
  indexing succeeds. Check mode skips indexing and service pauses.

## Unreleased — Daybook operations backup issues revocable FastDeploy tokens (2.31.11)

`daybook_operations_api_backup` (`tasks_from: register_echoport`) minted its
Echoport token with `deploy.auth.create_access_token`: 180 days, no `jti`, not
recorded in FastDeploy, so it could not be revoked and is rejected once
FastDeploy stops accepting legacy tokens. It also minted a new token on every
run. Rollout: requires FastDeploy with `commands.py issueservicetoken`; callers
must set `daybook_operations_api_backup_token_user` (ops-control does).

- The token is issued with `commands.py issueservicetoken` (argv, as the
  `fastdeploy` user, `no_log`), for `daybook_operations_api_backup_token_user`
  (required, an existing FastDeploy user), with
  `daybook_operations_api_backup_token_origin` (default `echoport`) and
  `daybook_operations_api_backup_token_days` (default 90, down from 180;
  values over 90 are refused before any change).
- Idempotent per run: the token stored in the Echoport target is inspected
  first (metadata only, never printed) and a new one is issued only when it is
  missing, undecodable, scoped to another service, has no `jti`, or expires
  within `daybook_operations_api_backup_token_renewal_days` (default 30).
  `daybook_operations_api_backup_rotate_service_token: true` forces a new one.
  The play reports the decision and the replaced token's id for
  `revokeservicetoken`.
- README: token section with the rotation steps.
- New test `tests/test_daybook_operations_service_token.py` (part of
  `just test-daybook-operations`): reuse decision, argv/`no_log`, task order,
  and that no role uses `create_access_token`.

## Unreleased — python-podcast private media in the production DB backup (2.31.10)

python-podcast keeps contributor voice references and the known-speaker
suggestion sidecar on the server filesystem
(`<site>/private_media/cast_voice_references`), deliberately off the public S3
bucket. The deploy keeps that directory across `rsync --delete`, but neither
backup covered it: the media runner copies only the S3 bucket and the
production DB runner only ran `pg_dump`. Losing the host lost the clips, and
the `ContributorVoiceReference` rows would point at missing files.

- `python_podcast_production_db_backup.py.j2` now also tars
  `pp_prod_db_backup_private_media_path` (default
  `/home/python-podcast/site/private_media`) on production, read-only and into
  a fresh private `mktemp -d` directory, after a `du` size guard
  (`pp_prod_db_backup_private_media_max_bytes`, default 2 GiB). It copies the
  archive back, checks every member (no traversal, links or special files,
  everything under the directory's own name, uncompressed size within the
  guard) and ships it as `private_media/private_media.tar.gz` inside the same
  uploaded archive, with its own `private_media` entry and SHA-256 in
  `manifest.json`. An empty path disables the step. A missing directory is a
  warning recorded in the manifest, not a failure; a failed probe, a symlink,
  or an oversized tree fails the backup.
- The staging restore skips private media by default and does not even
  extract it. The outer archive may no longer contain symlinks or hardlinks
  (this runner never writes any), so no link can route private media past
  that filter. Opt in with the locked role var
  `pp_prod_db_backup_restore_private_media: true` or `--include-private-media`
  on a manual run; Echoport's restore context cannot switch it on. When opted
  in, the archive checksum and members are verified before anything
  destructive, and the tree is swapped into
  `pp_prod_db_backup_restore_private_media_path` (owned by
  `pp_prod_db_backup_restore_private_media_owner`) while the services are
  stopped, keeping the old tree until the swap succeeds.
- New `tests/test_python_podcast_production_db_backup.py`
  (`just test-python-podcast-production-db-backup`, part of `just test`).

Rollout: the register playbook templates this runner straight from the
sibling `ops-library` checkout (`../../ops-library/roles/echoport_backup/...`),
so update that checkout to a release containing this change, then from
ops-control re-run `register-python-podcast-production-db-backup.yml`. No
ops-control variable is needed for the defaults. Optionally add the
`backup_private_media` and `restore_private_media` steps to the service's
`config.json` step list; FastDeploy creates unknown steps on the fly.

## Unreleased — Delve legacy iOS flags and recorder chunk cap (2.31.9)

`delve_deploy` could not set the backend's legacy switches, so a deploy of the
current Delve backend breaks sign-in for iOS builds that predate the
registration proof and the Sign in with Apple nonce.

- New `delve_profile_legacy_reregister` (`DELVE_PROFILE_LEGACY_REREGISTER`) and
  `delve_apple_signin_legacy_no_nonce` (`DELVE_APPLE_SIGNIN_LEGACY_NO_NONCE`).
  Set both to `true` for the deploy and switch them off once the new iOS build
  has been adopted; the role README documents the procedure under "Legacy iOS
  transition".
- New `delve_apple_server_notifications` (`DELVE_APPLE_SERVER_NOTIFICATIONS`)
  for the Sign in with Apple server-to-server webhook. `true` requires
  `delve_apple_client_id`, as the binary does.
- New `recorder_max_chunk_bytes` (`RECORDER_MAX_CHUNK_BYTES`) in
  `recorder_deploy` for the take upload chunk cap.
- All four default to empty and are written to the env file only when set.
  The Delve flags must be a boolean or `true`/`false` and are rendered as
  `"true"`/`"false"`; the chunk cap must be a positive integer. Other values
  fail validation instead of being silently ignored by the binaries.
- Variable names checked against ephes/podcast main
  (`apps/delve-backend/internal/config/config.go`,
  `apps/recorder/internal/config/config.go`).
- New `tests/test_delve_recorder_flags.yml` (`just test-delve-recorder-flags`,
  part of `just test`) covers defaults, rendering and validation.

Rollout: from ops-control, `just install-local-library`, set
`delve_profile_legacy_reregister: true` and
`delve_apple_signin_legacy_no_nonce: true` in the delve vars, then deploy
Delve. Recorder needs no redeploy unless the chunk cap is set.

## Unreleased — Run-scoped Molecule containers (2.31.8)

Molecule scenarios no longer use fixed Docker container names. 39 scenarios
named their platform `instance` (plus `debian13` and
`tailscale-metrics-endpoint`), and Molecule keyed its state directory by role
name only and its prerun reinstalled the checkout into the shared
`~/.ansible/collections`, so `just test` runs from two checkouts at the same
time destroyed or reused each other's containers and collection install
(`UNREACHABLE: Failed to create temporary directory`, rc 137 in
`os_apt_maintenance` and `ssh_restricted_forwarding_account`).

- Every `molecule.yml` platform name and `host_vars` key now ends in
  `-${MOLECULE_RUN_ID:-local}`.
- New `scripts/molecule-run.sh` runs every `just molecule-*` recipe (and
  `scripts/run-vaultwarden-molecule.sh`). It exports `MOLECULE_RUN_ID` (fresh
  per `molecule-test*` invocation, stable per checkout, role and scenario for
  converge, verify, login and destroy) and a run-scoped
  `MOLECULE_EPHEMERAL_DIRECTORY` and `ANSIBLE_HOME`, so Molecule's prerun
  install of the checkout as `local.ops_library` no longer races on (or
  leaks between checkouts through) `~/.ansible/collections`. The five
  scenarios that set `ANSIBLE_COLLECTIONS_PATH` now extend the wrapper's
  path instead of putting `~/.ansible/collections` first. After a failed or
  interrupted test the wrapper stops the whole Molecule process group, waits
  for detached Ansible async workers (the docker driver creates containers
  with `poll: 0`) so none can create a container after cleanup, and then
  destroys only its own run's containers.
- New `tests/test_molecule_run_isolation.py` (`just
  test-molecule-run-isolation`, part of `just test`) fails when a
  `molecule.yml` uses a fixed platform or network name such as
  `name: instance`, or keeps `host_vars` keys that match no platform, and
  checks the wrapper's run ID, state directory and cleanup behavior.
- The playbook-based tests in `tests/*.yml` no longer render to fixed `/tmp`
  paths, which a parallel run from another checkout overwrote or deleted
  mid-test (seen in the BIND secondary and Daybook photos symlink-safety
  tests). Their scratch paths now carry a per-checkout
  `ops_test_tmp_prefix` (a hash of `playbook_dir`), and
  `just test-bind-authoritative-secondary` renders into a private `mktemp`
  directory.
- `TESTING.md` documents how new scenarios name their platforms.

No role behavior changes. Branches that add Molecule scenarios must rename
their platforms the same way before merging.

## Unreleased — Voxhelm prune job and new service settings (2.31.7)

Nothing changes on deploy until the owner sets the new variables: the prune
job is off, and every new setting is left out of the env files (so each app
keeps its own default) unless it is set. Rollout: install this collection
version in ops-control; redeploy voxhelm, echoport or mailgun-relay only when
setting one of the new variables.

- `voxhelm_deploy`: optional hourly launchd job
  `de.wersdoerfer.voxhelm-prune` for `manage.py prune_job_artifacts` (Voxhelm
  D-09 retention). New `prune.sh` sources `voxhelm.env` like the worker; the
  plist uses `StartInterval` (`voxhelm_prune_interval_seconds`, default 3600)
  with `RunAtLoad` and `KeepAlive` false, and a deploy never kickstarts it.
  `voxhelm_prune_enabled` defaults to `false` because the first real run deletes
  the whole backlog; `voxhelm_prune_dry_run` defaults to `true`, so enabling the
  job alone only logs what it would delete. Disabling it unloads the job, fails
  if launchd still has it loaded, and then removes the plist and script. Enable steps are in the role README ("Job Artifact
  Pruning"). `voxhelm_remote_worker_deploy` never schedules pruning.
- `voxhelm_deploy`: optional `voxhelm_source_artifact_retention_seconds`,
  `voxhelm_job_metadata_retention_seconds`,
  `voxhelm_staged_input_retention_seconds`,
  `voxhelm_wyoming_stt_max_audio_seconds` and `voxhelm_private_url_hosts`,
  rendered as the matching `VOXHELM_*` settings only when set and validated
  before deployment.
- `echoport_deploy`: optional `echoport_stale_run_grace_seconds`,
  `echoport_late_result_window_seconds` and
  `echoport_health_overdue_grace_minutes` (`ECHOPORT_*` in `.env`), rendered
  only when set and validated as non-negative whole numbers.
- `mailgun_relay_deploy`: optional `mailgun_relay_smtp_max_concurrency`
  (`MAILGUN_RELAY_SMTP_MAX_CONCURRENCY`), rendered only when set; must be at
  least 1.
- New `tests/test_voxhelm_prune_and_service_knobs.py`
  (`just test-voxhelm-prune-and-service-knobs`, part of `just test`) renders
  the prune script and plist, the task gating, and the env files with and
  without the new settings, and runs the new validation tasks.

## Unreleased — FastDeploy legacy service token window (2.31.6)

FastDeploy now rejects service tokens without `jti` unless
`LEGACY_SERVICE_TOKENS_ACCEPTED_UNTIL` is set, and the deploy roles could not
set it. Rollout: install this collection version in ops-control before the
FastDeploy deploy; nothing changes until a variable is set.

- `fastdeploy_deploy`: new variables
  `fastdeploy_legacy_service_tokens_accepted_until`,
  `fastdeploy_service_token_max_expire_days` and
  `fastdeploy_service_token_retention_days`, rendered into `.env` as
  `LEGACY_SERVICE_TOKENS_ACCEPTED_UNTIL`, `SERVICE_TOKEN_MAX_EXPIRE_DAYS` and
  `SERVICE_TOKEN_RETENTION_DAYS` only when non-empty (all empty by default).
- `fastdeploy_self_deploy`: the same settings as `fd_self_*` variables in the
  release `.env`.
- Both roles validate the values before the `.env` file is written: the
  timestamp must be ISO 8601 with a UTC offset and a real calendar date, the
  day counts positive integers. In `fastdeploy_deploy` the check runs after
  the `postgres_install` dependency, like the existing secret checks.
- The `fastdeploy_deploy` README documents the cutover: set the grace period,
  deploy, re-issue tokens with `commands.py issueservicetoken`, clear the
  variable and deploy again.
- New test `tests/test_fastdeploy_service_token_settings.yml`
  (`just test-fastdeploy-service-token-settings`, part of `just test`).

## Unreleased — Restore safety (2.31.5)

- `vaultwarden_restore` (legacy path; Echoport stays the preferred restore)
  no longer overwrites the vault blind:
  - the staged `db.sqlite3` must exist and pass `PRAGMA integrity_check`
    before the service is touched;
  - symlinked `attachments`, `sends`, `db.sqlite3` or key files are refused
    before the stop, since the safety copy would only keep the link;
  - a failed stop aborts the run with the live data untouched (it was
    `failed_when: false`, so the DB could be copied under a running
    Vaultwarden);
  - after the stop it takes a timestamped safety copy of the data directory
    (DB with `-wal`/`-shm`, keys, attachments, sends) and of the config,
    systemd override and Traefik file under
    `vaultwarden_restore_safety_root` (default
    `/var/backups/vaultwarden-pre-restore`) and reports its path;
  - stale `db.sqlite3-wal`/`-shm`/`-journal` are removed before the copy, so
    SQLite cannot replay an old WAL over the restored database;
  - rsync and key copy failures are fatal (they were ignored, so a partial
    restore reported success);
  - any failure while overwriting puts the safety copy back and fails with
    Vaultwarden left stopped;
  - the decrypted archive on the controller and the remote staging directory
    are removed in `always`, also after a failure.
  `sqlite3` is now installed with `rsync`. New static test
  `tests/test_vaultwarden_restore_safety.py` (`just test-restore-safety`, part
  of `just test`); the molecule scenario now restores a real SQLite file and
  checks the WAL removal and the safety copy.

- `mastodon_restore` and `takahe_restore` no longer drop a live database
  for an unchecked dump:
  - the dump must pass `pg_restore --list` (with `TABLE DATA` entries) and a
    full `pg_restore --file=/dev/null` read before any service stops;
  - a failed service stop aborts the run before anything is dropped (it was
    `failed_when: false`); units that are not installed are skipped. With
    `<svc>_restore_stop_services: false` the services must already be
    stopped, or the run aborts;
  - after the stop the roles take a `pg_dump -Fc` of the live database
    (`<svc>_restore_safety_root`, default `/var/backups/<svc>-pre-restore`),
    a hard-link snapshot of the media (`<svc>_restore_media_safety_root`,
    default `/home/<svc>/media-pre-restore`; full copy across filesystems)
    and copies of the env, systemd, Traefik and nginx files, and report the
    paths. Media uploaded after the backup was lost to `rsync --delete`
    before;
  - `pg_restore` runs with `--single-transaction`;
  - the media `rsync --delete` adds `--ignore-times`, so every file gets a
    new inode and a metadata-only change cannot reach the hard-linked
    snapshot (the restore now rewrites all media files);
  - any failure while restoring (including migrations and the final start)
    restores the safety dump, media and config files, leaves the services
    stopped and fails with both safety paths. The rollback runs only when
    every service is confirmed stopped. The start no longer ignores
    failures;
  - the staging directory with the unpacked dump is removed in `always`.
  `takahe_restore` now also makes the staged dump traversable for the
  Postgres OS user, as `mastodon_restore` did. New defaults
  `<svc>_restore_postgres_dump_binary` and `<svc>_restore_postgres_psql_binary`.
  The safety dump needs free space for one compressed dump. New test
  `tests/test_fedi_restore_safety.py` (part of `just test-restore-safety`)
  checks the order statically and runs the snapshot, rollback and dump
  validation snippets against temp directories with stub binaries.

## Unreleased — Logyard ingress push-only (2.31.4)

`logyard_ingress_deploy` no longer forwards the whole Loki API. Loki runs with
`auth_enabled: false`, and the `logyard-int` router sent every path on the
host to it, gated only by client IP. Any LAN or tailnet device, and any process
on a VPS whose public IP is in the allow list, could query or tail every
host's journald logs and reach the delete API (Loki 3.5's default
`deletion_mode` is `filter-and-delete`, and the compactor has a delete request
store).

- The router now also requires a method and exact path from the new
  `logyard_ingress_allowed_paths` list. The default allows
  `POST /loki/api/v1/push` (Vector's `loki` sink) and `GET`/`HEAD /ready`
  (Vector's healthcheck and the documented validation curl). Every other path
  gets no route and returns `404`. The root redirect is unchanged.
- The role validates each entry (absolute, URL-safe path; non-empty list of
  upper-case methods) before rendering.
- Grafana is not affected: its Logyard datasource reads Loki over the docker
  network (`http://logyard-loki:3100`), and the health endpoint uses
  `127.0.0.1:3101`. Anything that queried Loki through the ingress host now
  gets `404`; query through Grafana or `127.0.0.1:3101` on the Loki host.
- New `tests/test_logyard_ingress.py` (`just test-logyard-ingress`, part of
  `just test`) and extended `tests/test_logyard_ingress_deploy.yml` check the
  rendered rule, that no `web-secure` router forwards a host-only rule to
  Loki, and that the root redirect is unchanged.

Rollout: from ops-control, `just install-local-library` and then
`just deploy-one logyard_ingress` (macmini, `deploy-logyard-ingress.yml`).
Traefik reloads the dynamic file on its own; producers keep pushing.

## Unreleased — Backups restart stopped services on failure (2.31.3)

A failed copy or dump step no longer leaves the service stopped. Rollout:
install this collection version in ops-control; the next backup run uses it. No
service needs a redeploy.

- `vaultwarden_backup`, `jellyfin_backup`, `navidrome_backup`,
  `metube_backup`, `takahe_backup`, `wagtail_backup` and `snappymail_backup`
  stop the service and copy the data inside one `block`; the restart is in its
  `always` section. Before, the restart was a later plain task, so an rsync,
  sqlite `.backup`, `pg_dump` or full-disk error aborted the play with the
  service down (Vaultwarden, Jellyfin, Navidrome, MeTube and Takahe stop by
  default). The play still fails, and the manifest, archive, fetch and
  retention steps still run only after a successful copy.
- These roles now restart only what they stopped: the stop result is
  registered, and a unit that was already inactive before the backup stays
  stopped instead of being started by the backup. A unit whose stop failed is
  still started.
- `mastodon_backup`: the service stop moves into the existing payload block, so
  the `always` restart also covers it.
- New static test `tests/test_backup_service_restart.py`
  (`just test-backup-service-restart`, part of `just test`): every backup task
  with `state: stopped` must sit in a `block` whose `always` starts the same
  unit.

## Unreleased — Failed mail dumps fail the backup (2.31.2)

- `mail_backup`: `pg_dump | gzip` ran without `pipefail`, so a failed dump
  (database down, authentication error, missing database) passed with an
  empty `database.sql.gz`, that empty backup was archived and fetched, and
  retention then aged out the older good backups. The dump now runs under
  `bash` with `set -euo pipefail`, goes to a `.tmp` file, is checked with
  `gzip -t`, must not be empty, and is renamed into place only then. The
  maildir tarball gets the same temp-file-and-rename treatment. Backup and
  archive steps run in a block: on any failure the incomplete timestamped
  directory and archive are removed and the play fails before retention runs.
  The role now refuses to start when this run's directory or archive already
  exists (a second run in the same play reuses the gathered timestamp), so
  the cleanup can never remove an earlier backup.
  Rollout: none needed; the next scheduled backup picks it up. A broken
  database now fails the backup run loudly instead of passing quietly.
- `mail_backup`: `manifest.yml` now gets group `mail_backup_group` (default
  `postgres`, like the rest of the backup) instead of `mail_backup_owner`,
  which was a typo. With the default owner `root` it was group `root`; with
  a non-root owner that has no group of the same name, the task failed.
- `mail_restore`: `database.sql.gz` is checked (`gzip -t`, not empty) before
  the existing database is dropped, and `gunzip | psql` runs with `pipefail`.
- `nyxmon_restore` ("Collect staging usage") and the Traefik basic-auth hash
  tasks in `echoport_deploy`, `homelab_deploy` and `minio_deploy` now use
  `pipefail` under `bash`, so a failed `du` or `htpasswd` fails the task
  instead of yielding an empty size or hash.
- New static check `just test-shell-pipefail` (`tests/test_shell_pipefail.py`,
  part of `just test`): every piped `shell` task in `roles/*/tasks` and
  `roles/*/handlers` must set `pipefail` and run under `bash`, unless it is
  allow-listed with a reason. It also runs the mail dump and restore check
  scripts with a stubbed `pg_dump`.

## Unreleased — Bearer tokens kept out of verbose output (2.31.1)

- `fastdeploy_register_service` and `echoport_backup`: the `POST
  /services/sync` call sends `Authorization: Bearer <token>` and now runs with
  `no_log: true`. Before, `ansible-playbook -vvv` printed the FastDeploy API
  token with the module arguments. A failed sync still does not fail the play;
  a new "Report failed service sync" task prints only the HTTP status and the
  response body, never the module's `msg` (it can quote request headers).
  Rollout: rerun either role; nothing on the
  host changes.
- New static check `just test-secret-no-log`
  (`scripts/check_secret_no_log.py`), run by `just test` and `just lint-strict`: a `uri` task
  that sends a credential (auth/token/API-key/cookie header, `url_password`,
  or a secret variable in the header value, URL or body) and a
  `command`/`shell`/`raw` task with an `Authorization:`/`Bearer` command line
  must have `no_log: true` on the task or an enclosing block. Molecule
  scenarios are not scanned. `TESTING.md` documents the rule.

## Unreleased — Opaq app deployment (2.31.0)

- New `opaq_app_deploy` deploys daybook's Opaq app, the company cash page,
  as Django + SQLite + WhiteNoise under gunicorn on loopback. The route has a
  Traefik `ipAllowList` on the HTTPS and HTTP routers, in front of the app's
  own password login.
  - The database lives outside the rsynced tree, so a sync can never remove
    it.
  - Only the `opaq-app` dependency group is installed; daybook's modules come
    from the synced `src/`.
  - The home, site, data and static directories are `0700`, and the env file
    and database `0600`. The unit runs with `ProtectSystem=strict`, only
    `data/` writable, no capabilities and `UMask=0077`.
  - The role creates no user and stores no password. The server gets only the
    upload token's SHA-256 digest.

## Unreleased — Secret file modes (2.30.2)

Files rendered with passwords or keys are no longer world-readable. Rollout:
rerun each changed role on its hosts (see the per-role notes); nothing changes
until then.

- `unifi_deploy`: the Mongo URI with the password is no longer an inline
  `Environment=MONGO_URI=...` in the `0644` unit (readable by every local user,
  also through `systemctl show`) and no longer appears in `ps`. It moves to a
  Java `@argfile` at `unifi_mongodb_jvm_args_path`
  (`/etc/unifi-secrets/mongodb.jvmargs`, `root:unifi 0640`, directory `0750`,
  `no_log`). Only the default directory is created; a custom path must point
  into an existing directory. `unifi_remove` deletes the file; `unifi_backup`,
  `unifi_restore` (restore and rollback) and the Echoport UniFi backup script
  carry it (`root:unifi 0640` on restore, written privately before it is moved
  into place). Backups taken before this release still hold the old unit;
  restoring one brings the inline password back, so rerun `unifi_deploy` after
  such a restore. Restored unit files are now explicitly `root:root 0644`.
- `fastdeploy_self_deploy`: the `fastdeploy` and `fastdeploy-staging` units load
  `DATABASE_URL` and `SECRET_KEY` from `/etc/default/<service>`
  (`root:root 0600`, `no_log`, values double-quoted with systemd escaping,
  checked against systemd's parser for quotes, backslashes, `$`, `%` and `#`)
  instead of inlining them. Unit files get explicit `root:root 0644`.
- `livekit_deploy`: `egress.yaml` (API secret, S3 keys, Redis password) is
  `root:root 0640` instead of `0644`. The egress image runs as user `egress`
  with primary group `root`, so it still reads the bind-mounted file. Both
  config templates are `no_log`.
- `minecraft_java_deploy`: `server.properties` is `0640` and `backup-world.sh`
  `0750` (both hold the RCON password, `no_log`). The script passes the
  password to mcrcon via `MCRCON_PASS` instead of `-p`, creates archives with
  `umask 077`, and each deploy tightens existing world backups to `0600`.
  `minecraft_java_backup` also uses `MCRCON_PASS`, writes archives `0600`
  (they contain `server.properties`) into a `0700` backup directory (the
  archive module sets the mode only after writing), and tightens older
  archives.
- `redis_install`: `redis.conf` (may contain `requirepass`) is
  `root:redis 0640` instead of `root:root 0644`, the direct-render path is
  `no_log`, and earlier `redis.conf.*~` backups are tightened the same way. The
  Docker validation fixture expects the new mode (not run for this change).
  README and docs page updated.
- `graphyard_vector_deploy`: the staged validation copies (ingest token, other
  fragments) are `0640` like the deployed files. They already lived in a
  private temporary directory.
- New `just test-secret-file-modes` (in `just test`): every template/copy task
  whose source uses a secret-named variable must set an octal mode without
  "other" bits, and systemd unit templates must not reference secrets.
  `TESTING.md` describes the rule.

## Unreleased — Strict ansible-lint baseline (2.30.1)

- `just lint-strict` now passes and fails on new findings. Existing debt is
  listed per file and rule in `.ansible-lint-ignore`, grouped with the reason
  it was not fixed: task-name prefixes, command/shell-instead-of-module,
  partial become, a few multi-line Jinja expressions, and all `roles/homelab_*`
  findings until the homelab lifecycle rework lands. `TESTING.md` documents
  the policy: fix new findings, delete entries as files are cleaned up.
  `just test` still runs only the lint summary.
- `paperless_restore`: the ownership reconciliation task passes its script as
  `shell: cmd: |`. ansible-lint could not split the free-form script (quotes
  in the SQL heredoc), so the whole `restore.yml` was never linted. The
  rendered command is unchanged.
- Meta fixes: platform names `Darwin`/`MacOS` become `MacOSX`
  (`fastdeploy_register_service`, `ollama_install`, `ollama_remove`,
  `uv_install`); `min_ansible_version` is quoted in the `ollama_proxy_*` and
  `open_webui_*` roles.
- Formatting only, no behaviour change: `block`/`rescue`/`always` moved after
  `when` in 31 tasks, Jinja spacing in 20 expressions, trailing spaces,
  missing `---` and extra blank lines removed, and the template moved to the
  end of a `minecraft_java_backup` task name.

## Unreleased — private static sites (2.30.0)

- `static_site_deploy` can publish private content. `static_site_private: true`
  syncs directories `0750` and files `0640` (root, service group) instead of
  world-readable `0755`/`0644`, creates the document root `0750`, and fails the
  run when anything under it is still accessible to others — on the first
  deploy and on every refresh. `static_site_traefik_allowed_networks` adds an
  `ipAllowList` to both the HTTPS and the HTTP-redirect router; where the
  Traefik entrypoint itself redirects HTTP to HTTPS (the macmini), that
  content-free redirect comes first and HTTPS enforces the list. Entries must
  pass the new `is_cidr` filter (strict `ipaddress` parsing, decimal prefix,
  unscoped address — what Traefik's Go parser accepts). Both default to today's
  behaviour; the benchmarks site renders and syncs exactly as before. First
  user: the private Opaq cash page on the macmini, tailnet only.

## Unreleased — Homelab backup/restore/remove safety fixes (2.29.1)

The homelab lifecycle roles get the fixes the review forced into their
`work_app_*` copies (2.27.0).

- `homelab_backup`: a failed service stop before the offline SQLite copy now
  aborts the backup instead of copying a live database.
  `homelab_backup_force_stop` is parsed with `| bool`.
- `homelab_restore`: the service is stopped before the safety snapshot, and a
  failed stop aborts the restore. Before that, the role requires `sqlite3` on
  the target when the archive contains a database. Stale `-wal`/`-shm`/`-journal`
  files are removed before the database is replaced. `PRAGMA integrity_check`
  must return exactly `ok`; before, only the exit code counted, and the check
  was skipped when `sqlite3` was missing.
- `homelab_remove`: all flags are parsed with `| bool`. `just remove-one homelab`
  passes `-e homelab_remove_auto_confirm=false` as a string, which skipped the
  confirmation pause before deleting the database and media. The user module
  only deletes the home directory when `homelab_remove_home` is true. The role
  refuses to keep the database or media while deleting the home directory or
  user they live in. The database path comes from `homelab_database_path`
  (its `-wal`/`-shm` files are removed too), media from `homelab_media_root`,
  and the service name from `homelab_service_name`.
- New regression test `tests/test_homelab_lifecycle_safety.yml`
  (`just test-homelab-lifecycle-safety`, part of `just test`).

## Unreleased — Private recursive resolver for rspamd (2.29.0)

- `mail_spam_deploy` can run a private recursive unbound instance for rspamd
  (`mail_spam_resolver_enabled`, default `false`). rspamd's blocklists
  (Spamhaus, SURBL, URIBL, DNSWL, Mailspike, ...) refuse lookups through public
  resolvers. On a host whose resolver forwards to 8.8.8.8 or 1.1.1.1, every
  blocklist symbol came back `*_BLOCKED` and scored nothing. The instance
  listens on `127.0.0.1:5335` with its own config and systemd unit
  (`unbound-rspamd`), leaving the host resolver untouched. rspamd uses it as
  `master-slave` primary with the host resolver as fallback. The role checks
  that it answers Spamhaus's test point before switching rspamd over. Package
  installation is opt-in (`mail_spam_resolver_install_packages`), because the
  `unbound` package also starts the distribution's instance on port 53.

## Unreleased — Edge recipient verification and spam filtering (2.28.0)

- `mail_relay_deploy` can verify port-25 recipients against the backend
  (`mail_relay_verify_recipients`, default `false`). Without it the edge accepted
  any local part in its domains, and the backend refused unknown ones only after
  that. The edge then bounced to the forged sender (backscatter): 20 such bounces
  in one month for a single made-up address. Unknown recipients now get a `550`
  at RCPT time. Probes for valid SRS bounce addresses are answered locally
  (`address_verify_default_transport`), so legitimate bounces don't depend on
  the original sender's MX accepting a probe.
- `mail_relay_postscreen_enabled` puts postscreen with DNSBL (Spamhaus ZEN,
  DNSWL as negative weight) and the pregreet test in front of port 25.
- `mail_relay_local_recursor_enabled` points systemd-resolved at a local
  recursor through a drop-in, with exactly one server, because DNSBLs refuse
  public resolvers. The role checks that the recursor answers the Spamhaus test
  point before switching.
- `mail_relay_submission_discard_spam` discards mail submitted on 587/465 whose
  top-level header carries the backend's spam verdict
  (`X-Spam-Status: Yes, ...`). The backend's alias forwards then no longer relay
  tagged spam to external addresses. Nested and MIME headers are not matched.
- The Molecule scenario covers all of these except the recursor.

## Unreleased — Work app lifecycle roles (2.27.0)

- New `work_app_shared`, `work_app_deploy`, `work_app_backup`,
  `work_app_restore` and `work_app_remove` roles for the work app (private
  `work-ledger` repository: Django + SQLite owner UI and coordinator API),
  modelled on the `homelab_*` roles. `work_app_deploy` rsyncs `src/` and
  `ledger/` from a local checkout into `/home/work/site`, runs
  `uv sync --frozen --no-dev --no-install-project`, renders `.env` (mode 0600),
  migrates, collects static files, and runs gunicorn
  (`src.config.wsgi:application`) as the `work-app` unit on `127.0.0.1:10011`.
  The systemd unit and the dual router Traefik config (LAN/Tailscale without
  auth, public with the shared basic auth) go through `webapp_deploy_internal`.
  The deploy ends with an HTTP check of `/accounts/login/`. Backup, restore
  and remove follow `homelab_backup`, `homelab_restore` and `homelab_remove`
  without the media and cache parts the app does not have; remove refuses to
  delete the home directory while keeping the database inside it. Unlike the
  homelab originals, a failed service stop aborts the offline backup and the
  restore (which now stops the service before its safety snapshot), restore
  requires `PRAGMA integrity_check` to return `ok`, and remove parses its flags
  with `| bool` and keeps the home directory when `work_app_remove_home` is false.
  `tests/test_work_app_deploy.yml` (`just test-work-app-deploy`) covers the
  defaults, the rendered env, unit and Traefik files, and the secret-key guard.

## Unreleased — Keep rspamd in the Postfix milter chain (2.26.4)

- `mail_backend_deploy` gains `mail_backend_extra_milters` (default `[]`).
  It templates the whole `main.cf`, and its `smtpd_milters` used to be
  hard-coded to OpenDKIM. So every backend deploy dropped the rspamd milter
  that `mail_spam_deploy` had appended. rspamd kept running and passed its
  health checks, but scanned nothing. List `unix:rspamd/milter.sock` here
  wherever both roles run. `non_smtpd_milters` is now `$smtpd_milters`, the
  form `mail_spam_deploy` writes, so the two roles no longer rewrite each
  other's line.
- `mail_backend_deploy` can install a global `sieve_before` script that files
  mail tagged `X-Spam-Status: Yes` or `X-Spam: Yes` into Junk
  (`mail_backend_spam_to_junk_enabled`, default `false`;
  `mail_backend_spam_junk_mailbox`, `mail_backend_sieve_before_dir`).
- `mail_spam_deploy`:
  - An action threshold set to `null` disables that action. A backend behind
    a relay should disable `reject` (it causes backscatter) and `greylist`.
    A `null` greylist threshold also disables the greylist module, which
    otherwise forces `soft reject` on its own.
  - `mail_spam_local_addrs_extra` and `mail_spam_external_relay_enabled` make
    rspamd score the real sender behind a trusted relay instead of the relay
    itself. Without them, a relay without rDNS adds 4.5 points to every
    message.
  - `x-spam-status` is added to the default `milter_headers`
    (`mail_spam_milter_headers`).
  - `redis.conf` is written with mode `0640`, since it can hold the Redis
    password.
  - The configuration is validated with `rspamadm configtest`.
  - Check mode reads the current `smtpd_milters`. It used to start from an
    empty list, so `--check --diff` showed OpenDKIM being dropped.
  - The README no longer claims that moving mail into Junk trains the filter.

## Unreleased — Never rsync Ansible Vault passwords (2.26.3)

- Every role that rsyncs a project tree now excludes `.vault_password` by
  default: `wagtail_deploy`, `takahe` (`takahe_rsync_excludes`), `marina_deploy`,
  `heis_deploy`, `nyxmon_deploy` (both lists), `graphyard_deploy`,
  `logyard_deploy`, `opsgate_deploy`, `mailgun_relay_deploy`, `voxhelm_deploy`
  (`voxhelm_sync_excludes`) and `fastdeploy_deploy`. Project checkouts still
  carried gitignored `deploy/.vault_password` files from their pre-ops-control
  Ansible flows, and rsync shipped them as world-readable files (mode 644)
  into the service's site directory, next to the vault-encrypted
  `deploy/secrets*.yml` they unlock.

## Unreleased — Python 3.14.8 and tool pin refresh (2.26.2)

- `homeassistant_deploy`, `wagtail_deploy`, `voxhelm_deploy` and
  `voxhelm_remote_worker_deploy` pin Python 3.14.8 (was 3.14.6/3.14.7). The
  patch release fixes seven CVEs, among them tarfile extraction-filter bypasses,
  a use-after-free in SSL SNI callbacks and urllib credential leakage. uv 0.12.22
  is the first release whose catalog has 3.14.8; each role's uv install step
  tracks `latest`, so older uv binaries are updated before the interpreter is
  requested.
- `homeassistant_deploy` and `wagtail_deploy` now restart their services when
  they install a new Python patch. `uv python install` moves uv's
  `cpython-<minor>` link, and virtualenvs created on that link immediately
  report the new patch. The roles' version-mismatch checks therefore saw
  nothing to rebuild, and the running processes stayed on the old
  interpreter until some unrelated restart. Home Assistant now also restarts
  the Matter server when `homeassistant_manage_matter_server` is set.
- The Daybook roles stay on 3.14.7 for now. Their bump is a planned-window
  procedure: stop the supervisor, deploy, replace, cutover. For
  `daybook_photos_archive_sync_deploy` it also needs Full Disk Access granted
  again (see ops-control `docs/DAYBOOK_PYTHON_RUNTIME_PLAN.md`).
- `vibe_coding_deploy`: Neovim 0.12.4 -> 0.12.5, lazygit 0.63.1 -> 0.65.1.
- `mastodon_shared`: nvm v0.40.6 -> v0.40.8.
- `sops_dependencies`: age 1.3.1 -> 1.3.2.
- `software_estate` stays on Syft 1.52.0: the SBOM adapter and its tests
  must be updated before that version changes.

## Unreleased — Navidrome 0.64.2 and Paperless-ngx 3.2.1 (2.26.1)

- `navidrome_deploy` installs Navidrome 0.64.2 (was 0.63.2), with both
  `navidrome_checksums` updated. 0.64.0, 0.64.1 and 0.64.2 fix several security
  advisories, among them SQL injection in the Native API, share IDOR, unthrottled
  Subsonic logins and an `X-Forwarded-For` rate-limit bypass. 0.64.0 re-encodes
  every internal ID in a migration that touches every table, so take a
  `navidrome_backup` first. Clients that cache item IDs may need to re-sync.
  Negative config durations are now rejected and unknown options are logged;
  the rendered `navidrome.toml` uses neither.
- `paperless_deploy` installs Paperless-ngx 3.2.1 (was 3.0.4) and gains its
  `paperless_release_checksums` entry. 3.1.2 fixes GHSA-2jhj-xqrq-rmrq. There are
  no breaking changes for bare-metal installs between 3.0.4 and 3.2.1.

## Unreleased — OpenClaw Doctor activation (2.26.0)

- `openclaw_deploy` activates a new OpenClaw image through Doctor on
  v2026.9.7 and later (`openclaw_doctor_activation_enabled`, default `true`).
  When the gateway container is missing or runs a different image, the role
  stops the gateway and runs the official entrypoint's
  `openclaw doctor --fix --non-interactive` with the new image and host
  networking, before plugin inspect/install or secrets apply open the state.
  Without it, the first 9.7 CLI call migrated the shared state database from
  schema 17 to 19 underneath the still running 9.4 gateway, and the pinned
  Codex plugin install was refused until Doctor had converged the plugin's
  data. A failed Doctor keeps the gateway stopped; deploys that keep the
  running image are unaffected.

## Unreleased — Redis candidate configuration installation (2.25.2)

- With `redis_install_validate_config=true`, render Redis configuration into a
  private candidate, validate it, then atomically install it. Invalid candidates
  and handled validator interruption preserve the running service, active file,
  metadata and existing backups. Unchanged candidates are still validated without
  a restart, and ephemeral candidate/script directories are removed. Check mode
  predicts changes without starting validation. Validation remains opt-in; this
  does not roll back a valid installation if a later restart fails. Signals during
  validator cleanup now defer failure exit until termination and removal finish,
  including interrupted polling sleeps.

## Unreleased — Redis optional config validation (2.25.1)

- Fix `redis_install_validate_config=true` rejecting valid Redis configurations
  because port 0 with no Unix socket provides no listener. Validation now uses a
  private temporary Unix socket, disables supervision, and cleans up its process
  and artifacts. Invalid configuration still stops before service restart; the
  rendered file remains on disk and must be corrected before a later restart.

## Unreleased — Daybook on a pinned uv-managed Python (2.25.0)

- No Daybook role builds on Homebrew's Python any more. A `brew upgrade` whose
  cleanup deleted the framework the Voice Memo importer's copied interpreter
  linked to stopped every scheduled Studio run. `daybook_voice_memo_inbox_deploy`
  and `daybook_voice_memo_attention_deploy` now install a uv-managed CPython of
  exactly `*_python_version` (`3.14.7`) as root into the root-owned
  `/Library/Application Support/Daybook/python`, assert the binary is root-owned
  and not group- or world-writable, and replace `*_python_source` (removed).
  `daybook_operations_runtime_deploy` (its own code path, as on Atlas),
  `daybook_photos_offload_deploy`, `daybook_photos_archive_sync_deploy` and
  `daybook_sessions_deploy` pin the same exact patch with
  `UV_PYTHON_PREFERENCE=only-managed`.
- Interpreters are requested by version, never by path: a venv created from a
  path records uv's movable minor-version link as its home. Every role asserts
  after the sync that the environment runs exactly the pinned version.
- An environment built on another interpreter is removed and rebuilt (uv aborts
  on one whose interpreter cannot start); the photos-offload, photos-archive-sync
  and sessions roles remove an environment whose interpreter does not start. In the runtime role this counts as an
  environment change and is refused while a supervisor may run it, because
  `uv sync --check` answers 0 while it would replace such an environment.
- The importer README now records that the scheduled path reads Voice Memos
  through the capability host's Full Disk Access grant (`mode: host`); the
  interpreter's own grant matters only for its direct label and first
  activation.

## Unreleased — USB offsite rotation (2.24.0)

- `zfs_usb_replication` can rotate several offsite drives that share one pool
  name (`zfs_usb_replication_devices`). Each attached drive is imported from
  its own partitions (optionally pinned by `pool_guid`), replicated and
  exported in turn; status is kept per drive under `devices` while the
  top-level summary stays compatible. The new `bookmark` anchor mode
  replicates with `--no-sync-snap` and keeps every drive's incremental base as
  a source bookmark, pruned only once no drive of the rotation needs it.
  Retention never prunes a bookmark-held anchor and skips targets that do not
  exist yet. `backup_metrics_endpoint_usb_devices` reports any present drive
  and passes the per-drive state through.

## Unreleased — mail organization (2.23.1)

- Document opt-in `mail.review.v1` organization, quoted enrollment cutoff, scheduled
  Keychain acceptance, API-first compatibility and rollback preserving journals.
  The role continues to pass adapter settings to the pinned client for validation.

## Unreleased — operations API (2.23.0)

- `daybook_operations_runtime_deploy` accepts `mail.review.v1` for explicit mail follow-up cohorts.

## Unreleased — operations API (2.22.0)

- New role `macos_smb_mount_keeper`: a user LaunchAgent that remounts SMB shares
  at their exact `/Volumes/<share>` path with Finder's `mount volume` and the
  login keychain's credential, at load and every five minutes by default. It
  leaves an occupied mount point or a share mounted elsewhere alone and only
  logs it, never unmounts or deletes anything, and logs only a change of outcome.
- `daybook_operations_runtime_deploy` accepts `catalog.work.v1` (the Daybook
  vault catalogue) in its adapter allowlist. Atlas's profile renders the kind
  from daybook 94cac7c on; without it the role refused the profile before the
  client could load it.
- `daybook_operations_runtime_deploy` accepts the two Photos kinds of work,
  `photos.archive_sync.v1` (the Nikon working-folder sync, Atlas) and
  `photos.archive.v1` (Daybook's complete Photos archive, Studio). Both exist in
  Daybook `main`, and ops-control declares them behind per-machine flags; until
  now a profile naming either failed the role's kind validation before the
  client could load it.
- New role `daybook_catalog_access_deploy`: the MinIO identity the Daybook vault
  catalogue writes with (`daybook-catalog-writer`: list only the three
  `Katalog/<repository>/` prefixes of `obsidian`, get and put only under
  `obsidian/Katalog/*`, no delete), provisioned fail closed by the same
  provisioner as `daybook_work_source_access_deploy` (`mode: server`), and its
  owner-private credentials file and lane directories on the machine that runs
  the lane (`mode: client`, user-owned for Atlas). Not yet deployed anywhere.
- `daybook_sessions_deploy` renders `DAYBOOK_WEEKNOTES_CONFIDENTIAL_NAMES` from
  `daybook_weeknotes_confidential_names_json` (a JSON list, required) into the
  weeknotes reconcile environment: the configured names public weeknotes must
  never carry, replacing the aliases Daybook used to derive from session
  directories.
- `daybook_voice_memo_inbox_deploy` deletes the long-lane plist once
  `daybook_voice_memo_inbox_long_label_enabled: false` has proven the label
  absent, and no longer renders it while retired; setting the flag back renders
  it again.
- `daybook_sessions_deploy` refuses to write the weeknotes reconciler's
  environment without the verified `monday-after-v1` epoch once its unit is
  retired. The `weeknotes` source reads that file on every run and, without the
  epoch, refuses all work; an ordinary deployment in the first Studio window had
  rewritten it without, and the first timed run failed both audiences
  (`source_unavailable`).
- Close out the Daybook machines once every scheduled job runs under the
  operations supervisor. `daybook_operations_runtime_deploy` gains
  `action: closeout`: it deletes the label's saved original command and writes a
  `closed-out` marker, after which `rollback` refuses and a later `cutover` saves
  nothing; it touches nothing else. `daybook_voice_memo_work_retired`,
  `daybook_mail_work_retired` and `daybook_weeknotes_reconcile_launchd_retired`
  (each only with the job disabled) delete the job's plist once its label is
  proven unloaded, keeping the configuration the supervisor's sources run from.
- `daybook_operations_runtime_deploy` no longer changes a running supervisor's
  environment on a redeploy of the same revision: it asks `uv sync --check`
  first, syncs only when the environment is out of date, and refuses that (as it
  already refused replacing the checkout) while the supervisor label is loaded or
  an `operations serve` runs.
- `daybook_voice_memo_inbox_deploy` does the same for Studio's protected
  checkout: `git init` and a fetch of every ref of the bundle instead of a clone.
- `daybook_operations_runtime_deploy` installs the code by fetching every ref of
  the bundle into a fresh repository instead of cloning it, because the bundle now
  carries Daybook `main` as `refs/remotes/origin/main` (production runs main,
  never a branch) and a clone takes only branches, so it arrived empty.

- Generalise `daybook_operations_runtime_deploy` for a second machine and for the
  supervisor inside a capability host. `daybook_operations_runtime_owner: user`
  makes the install, profile and LaunchAgent the GUI user's, for a machine
  deployed without root (Atlas), and the plist passes `--policy-owner`.
  `daybook_operations_runtime_mode: host` runs `operations host-keep`, which keeps
  the supervisor alive inside the machine's capability host. The profile is
  schema 5 (per-kind `long` and `run`; the importer policy moves into the memo
  kinds), and is proven loadable by the installed client at deployment. An
  optional git bundle installs the pinned code on a fresh machine, never over code
  a supervisor may be running. Transitions also refuse while a hosted
  `operations serve` still runs, and handle a label that never ran anything.
- Add `daybook_sessions_launchd_enabled` and
  `daybook_archive_quote_classifier_launchd_enabled` to `daybook_sessions_deploy`:
  `false` retires that launchd timer (refused while it runs; unloaded, disabled,
  plist removed, proven gone) while keeping the environment file, launcher and
  checkout the Daybook operations supervisor now runs the same work from.

- Document how to choose `daybook_mail_work_interval_seconds` in the
  `daybook_mail_work_deploy` README, with the measurement behind it. The default
  of 300 is probably too short for a judgement-heavy source: measured on one
  host over 20.5 hours of steady running, 50 of 58 five-minute windows held
  exactly one message and the 58 carried 68 in total, so every message got a
  full agent session instead of the window being the unit of work. A table simulates 5 to 120 minutes against those same arrivals — an
  hour gives 21 sessions a day averaging 3.8 messages, against 68 averaging 1.2.
  The default is unchanged; this only makes the trade-off visible.

- Add operations capacity monitoring to the API role: executor/monitor credential
  purposes in versioned profile entries, rendered capacity thresholds, nominal
  growth and an operator-configured storage sampling path. Legacy executor-only
  profile entries keep working; a monitor token may never also be an executor
  token. Documented in the role README; not deployed.
- Add a fixed-source, backup-only Echoport bridge with private staging and verified upload; preserve attended restore requirements.
- Fix macOS runtime user switching from root-only SSH working directories and
  allow the unprivileged restore helper to replace its private configuration atomically.
- Add disabled-first Daybook JSON API and protected macOS importer runtime roles.
- Add private database/keyring backup, guarded restore with stopped services, and evidence-preserving removal.
- Stage regular-label cutover/rollback without changing long/native-work labels. Live rollout remains separately gated.

All notable changes to the ops-library collection will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

- Add a guarded `metrics_bind` Traefik transaction that can only replace an
  implicit public Prometheus listener with an explicit loopback-only
  `127.0.0.1:8080` entrypoint while preserving every unrelated static setting,
  the binary, dynamic routes, unit identity, rollback, and recovery interlocks.

- Default Traefik deployments to 3.7.13, addressing upstream advisories
  [GHSA-qqjf-53cj-pwvv](https://github.com/traefik/traefik/security/advisories/GHSA-qqjf-53cj-pwvv),
  [GHSA-f52w-8j3h-j724](https://github.com/traefik/traefik/security/advisories/GHSA-f52w-8j3h-j724),
  [GHSA-v67p-phpq-fc8x](https://github.com/traefik/traefik/security/advisories/GHSA-v67p-phpq-fc8x),
  [GHSA-w4v4-9rw7-5326](https://github.com/traefik/traefik/security/advisories/GHSA-w4v4-9rw7-5326),
  and [GHSA-8fcf-v89g-xpg6](https://github.com/traefik/traefik/security/advisories/GHSA-8fcf-v89g-xpg6).

### Fixed

- Select Debian 13's packaged `named.conf.root-hints` include in
  `bind_authoritative_deploy`; trixie removes `named.conf.default-zones`, which
  otherwise leaves BIND half-configured during an in-place upgrade.

- Replace Tailscale's deprecated one-line `apt_repository` path with deb822 and
  clean up the legacy `.list` file, avoiding the deprecated one-line repository
  path on Debian 13.

- Prevent explicitly retired legacy Takahe routes from bypassing the managed
  nginx cache by removing them only after rendering the replacement route.

### Changed

- `daybook_mail_work_deploy` now passes `--rotate-log` for the courier's two
  launchd logs (`daybook_mail_work_rotate_logs`, default `true`), so the Daybook
  CLI copy-and-truncates them at 1 MiB; the same CLI release prunes attempt
  directories on every tick. Update the host's Daybook CLI before deploying, or
  set the variable to `false`, because an older CLI rejects the option.

- `daybook_sessions_deploy` now defaults `daybook_sessions_checkout_path` to a
  dedicated clone under `~/.local/share/daybook/sessions/daybook` instead of the
  service user's `~/projects/daybook`. The scheduled jobs pin that path to
  `daybook_sessions_repo_ref`, and sharing it with an interactive clone meant a
  routine `git pull` stopped the weeknotes reconcile at its revision guard for
  two weeks. Hosts that relied on the old default must either set the previous
  path explicitly or stage the new clone before the next no-fetch deployment.

### Added

- Configure an optional dedicated read-only Graphyard inventory monitor credential
  in the protected environment. Weekly release refresh now bypasses the success
  cache so a recent manual run cannot postpone scheduled source freshness.

- Read SnappyMail and PostfixAdmin installed artifact metadata through bounded,
  root-owned paths without executing application code or reading configuration.

- Resolve the emitter CLI test spool path on macOS without weakening symlink checks.

- Bind explicit related systemd units from the existing local inventory,
  preserving source errors and missing-unit coverage without additional probes.

- Add optional weekly public release comparison scheduling to Graphyard, using its existing unprivileged account and preserving refresh locks during rsync.

- Optionally export existing local software-health metadata for the unprivileged
  inventory publisher, preserving source timestamps and explicit coverage gaps
  without granting monitoring credentials or adding cross-host collection.

- Add an opt-in `preserve_partial_applications` policy boolean to retain application
  probe evidence in failed inventory reports without claiming complete coverage.
  Upgrade the Graphyard receiver before enabling this schema extension.

- Support operator-initiated remote installation of the host-local macOS inventory
  publisher, with target-side Python validation and private initial writer
  provisioning that preserves existing credentials. Installation now requires the
  observed hostname in the configured lowercase hostname allowlist.

- Add a Linux/systemd local inventory publisher with a dedicated unprivileged
  identity, persistent weekly cadence, hourly HTTPS delivery, retained outbox
  on removal, and a privilege-dropping manual entry point.

- Add a local macOS `software_estate_publisher` LaunchAgent with weekly scan
  cadence, hourly eligible delivery, private durable state, shared manual-run
  locking and removal that retains unconfirmed reports and credentials.

- Add opt-in private Graphyard inventory ingress with source allowlisting, 8 MiB
  body limit and independent rate/concurrency limits; existing UI/metric routes
  remain unchanged. Inventory writers still authenticate at the application.

- Add source-run direct HTTPS inventory delivery with durable retry/block state,
  strict acknowledgment validation and shared outbox locking. Reports are removed
  only after confirmed storage. Existing Vector log/metric routes are unchanged;
  no scheduler or production inventory rollout is installed.

- Add opt-in local inventory report emission and isolated Vector config generation; source-run pilot helpers do not install schedules or remote access.

- Add read-only software estate discovery and explicit coverage evidence for
  host packages, service state, container identities and registered applications.
  Private estate reports preserve configured intent separately from live state.

- Declare Debian 13/trixie support for the staging package, repository,
  application, DNS, logging, SSH/base, static-site, and systemd-mask roles.
  PostgreSQL 17, Redis, Tailscale, and shell package paths now run in real
  Debian 13 Molecule containers, with focused release/repository contracts for
  the remaining staging roles.

- Extend `software_live` with OS lifecycle and PostgreSQL cluster/version
  observations. Schema version 2 exposes desired-cycle/major drift, support and
  EOL status, PostgreSQL minor drift and unexpected clusters for Nyxmon warning
  checks without changing packages or database state.

  This schema change requires `os` and `postgresql` policy mappings in existing
  inventory. Previously written schema-1 state is rejected until the upgraded
  collector writes schema-2 evidence.

- `zfs_usb_replication` now installs an attended, root-private snapshot-file
  replication attestation helper. Closed bounded requests bind exact relative
  paths, byte counts, and SHA-256 digests to the newest source snapshot whose
  preserved GUID is also present on a distinct read-only replica pool. The
  helper uses only bounded, absolute-path `zfs list/get` and `zpool get` calls,
  descriptor-safe source-snapshot reads, post-hash snapshot re-observation, and
  atomic mode-`0600` responses. It deliberately does not run from the scheduled
  replication service and makes no claim about retention, independent failure
  domains, or physical offsite custody.

- Add `takahe_traefik_legacy_config_paths` and the `takahe_traefik` tag for
  opt-in legacy-route migration and routing-only updates.

- Add a daily index-only apt refresh to `os_apt_maintenance`
  (`os-apt-maintenance-refresh.timer`, `--refresh-only`). The weekly
  maintenance timer cannot hold the 48-hour apt index freshness budget that
  `software_live` enforces, so hosts without `unattended-upgrades` performing an
  incidental daily `apt update` reported `pending_security_count: 0` from
  week-old indexes. The refresh installs nothing, shares the maintenance lock,
  and never writes `state.json`. Disable with
  `os_apt_maintenance_refresh_enabled: false`.

### Security

- Add a guarded `metrics_bind` Traefik transaction that can only replace an
  implicit public Prometheus listener with an explicit loopback-only
  `127.0.0.1:8080` entrypoint while preserving every unrelated static setting,
  the binary, dynamic routes, unit identity, rollback, and recovery interlocks.

- Default Traefik deployments to 3.7.13, addressing upstream advisories
  [GHSA-qqjf-53cj-pwvv](https://github.com/traefik/traefik/security/advisories/GHSA-qqjf-53cj-pwvv),
  [GHSA-f52w-8j3h-j724](https://github.com/traefik/traefik/security/advisories/GHSA-f52w-8j3h-j724),
  [GHSA-v67p-phpq-fc8x](https://github.com/traefik/traefik/security/advisories/GHSA-v67p-phpq-fc8x),
  [GHSA-w4v4-9rw7-5326](https://github.com/traefik/traefik/security/advisories/GHSA-w4v4-9rw7-5326),
  and [GHSA-8fcf-v89g-xpg6](https://github.com/traefik/traefik/security/advisories/GHSA-8fcf-v89g-xpg6).

### Fixed

- Allow Mastodon backup fetches to disable privilege escalation when the SSH
  user can read the archive directly. This avoids Ansible's in-memory `slurp`
  fallback exhausting controller memory on large production archives.

- Preserve target-local Graphyard `src/django/.env` during source synchronization;
  exclude developer copies from upload as well.

- Resolve the inventory writer credential through Vector's directory secret backend
  at `<data-dir>-secrets/writer`. Environment interpolation is disabled by default
  in current Vector; the previous placeholder was sent literally and rejected.
  Stop the separate pilot, back up its old config, provision a private 0600
  credential file and regenerate the config while retaining outbox/buffer state.
  Keep secrets outside the buffer directory and reject insecure existing paths.
  Real Graphyard integration exposed intermittent low-traffic stalls in Vector
  0.58, including with one worker; unattended inventory delivery remains blocked.

- Initialize SSH forwarding identity test fixtures with the configured primary
  group so macOS group inheritance does not bypass the intended race regressions.
  Production owner/group checks remain unchanged and are explicitly tested.

- Reject empty/duplicate application IDs before collection and preserve missing
  package/version evidence and nested Git/Python failures in the pilot applications
  category. Keep spool and Vector data paths separate; typecheck helper bodies.

- Select Debian 13's packaged `named.conf.root-hints` include in
  `bind_authoritative_deploy`; trixie removes `named.conf.default-zones`, which
  otherwise leaves BIND half-configured during an in-place upgrade.

- Replace Tailscale's deprecated one-line `apt_repository` path with deb822 and
  clean up the legacy `.list` file, avoiding the deprecated one-line repository
  path on Debian 13.

- Prevent explicitly retired legacy Takahe routes from bypassing the managed
  nginx cache by removing them only after rendering the replacement route.

### Changed

- `daybook_sessions_deploy` now defaults `daybook_sessions_checkout_path` to a
  dedicated clone under `~/.local/share/daybook/sessions/daybook` instead of the
  service user's `~/projects/daybook`. The scheduled jobs pin that path to
  `daybook_sessions_repo_ref`, and sharing it with an interactive clone meant a
  routine `git pull` stopped the weeknotes reconcile at its revision guard for
  two weeks. Hosts that relied on the old default must either set the previous
  path explicitly or stage the new clone before the next no-fetch deployment.

## [2.21.1] - 2026-09-14

### Fixed

- Declare the managed OpenClaw OpsGate tool in the plugin manifest so OpenClaw
  2026.9.4 registers it instead of reporting a missing `contracts.tools` error.

## [2.21.0] - 2026-09-08

### Added

- Allow verified SSH recovery for proxy-only transactions and provide read-only ingress/static-alias acceptance probes.

- Add journaled pre-enrollment ownership repair and inactive-service retirement; preserve application data and proxy PID.

- Optional OpenClaw v2026.9.1 heartbeat recovery extension preserves structured
  notification decisions during incomplete-turn retries and blocks direct
  message sends in those recovery runs.

## [2.20.0] - 2026-09-07

### Added

- Guarded Traefik binary and alias-only transaction entry with exact checksums,
  runtime identity verification, atomic replacement, rollback and paired recovery
  records. Operator evidence and reviewed acceptance/cleanup programs are required.
- Legacy Traefik full deploy, restore and removal guards for transaction-managed
  hosts; future template rendering preserves approved header-alias policy.

## [2.19.0] - 2026-09-07

### Added

- `software_live` provides shared read-only Traefik disk/process/version drift and
  cached APT security-update observations, a hardened periodic collector and a
  Tailscale/loopback-only authenticated JSON endpoint. Unknown/stale observations,
  held security updates and failed upstream lookups remain visible.
- Targeted Nyxmon check upsert/disable task entries and `software_live_remove`
  complete monitoring lifecycle without changing monitored applications.

### Fixed

- Restore usable pre-commit validation with the project's Ansible toolchain,
  a local Jinja syntax parser, secret scanning without a missing baseline, and
  Markdown settings compatible with role tables and historical release notes.
- Exclude mutable mypy/Ruff caches from collection artifacts so concurrent checks
  cannot create checksum-invalid deployment archives.

<!-- Historical release sections repeat category headings. -->
<!-- markdownlint-disable MD024 -->

## [2.18.0] - 2026-09-07

### Added

- `macos_ssh_tunnel` manages an independent user LaunchAgent for a loopback
  SSH local forward, with persistent start/stop controls and an HTTPS health
  check. Installation defaults to stopped and certificate verification is
  enabled unless the private caller explicitly opts out.

## [2.17.0] - 2026-09-07

### Added

- Archive deployment validates log overrides beneath the private log tree and
  the virtualenv beneath the verified checkout; actual Ansible assertion tests
  reject outside, relative, and traversing overrides for all managed paths.
- Included the archive role in rendered documentation and its pytest regression
  module in the default test recipe.
- Added `daybook_photos_archive_sync_deploy`, a disabled-first macOS Aqua
  LaunchAgent for a single Nikon archive writer. It installs an exact bundled
  Daybook revision, protects private state/logs, requires an existing SMB mount,
  and keeps installation separate from activation. The same-runtime Photos
  preflight exits 77 within 15 seconds when launchd cannot read `Photos.sqlite`;
  interval validation includes both watchdog grace periods.
- Documented the repaired Daybook source-root migration, immutable recovery,
  creation-ownership evidence, and repeated-lock escalation. Deployment remains
  disabled until an exact repaired revision is separately reviewed and installed.

### Fixed

- Keep the copied Nikon source bundle beneath the install root. Validation-only
  tests select named assertion tasks and reject any other executable task keys.

## [2.16.1] - 2026-09-07

### Fixed

- `voxhelm_deploy` now renders configurable `VOXHELM_CSRF_TRUSTED_ORIGINS`
  for the application's existing HTTPS operator-login support. The default is
  an empty list; callers supply explicit trusted origins.

## [2.16.0] - 2026-09-07

### Added

- Added `static_site_deploy` in collection 2.16.0, a reusable controller-to-host
  publication role for compact generated sites. It permits only regular files and directories
  in the source, syncs deterministic modes into a root-owned document root,
  serves it on loopback with a hardened systemd unit and disabled directory
  listings, renders an HTTPS Traefik route, and can verify both local and public
  serving paths.

- Added `daybook_voice_memo_work_deploy`, a separate five-minute macOS
  LaunchAgent for capable work on newly imported memos, and
  `daybook_work_source_access_deploy` for its dedicated source identity.

- Added `daybook_voice_memo_attention_reader_deploy` for a dedicated MinIO identity
  with exact-prefix listing and object reads only. It rejects policy, group,
  ownership, and credential drift rather than adopting existing identities.
  Input validation rejects CR/LF in secrets and option-like access keys before
  running MinIO commands.

- Added `daybook_voice_memo_attention_notifier_deploy` and
  `daybook_voice_memo_attention_notifier_remove` for a recipient-pinned
  outbound-only notifier with a dedicated restricted SSH key. Installation does
  not send messages and preserves existing administration keys.

- Added disabled-only `daybook_voice_memo_attention_deploy` and state-preserving
  `daybook_voice_memo_attention_remove` macOS roles. The pilot installs a provided
  Daybook wheel in a separate environment and an unloaded persistent `serve`
  LaunchAgent with failed-exit restarts throttled to 900 seconds;
  it rejects activation and does not initialize tracking or touch the importer.

- `wagtail_deploy` gained `wagtail_require_object_storage` and
  `wagtail_require_sentry` (both default `true`, so existing deployments are
  unchanged). Setting either to `false` skips the corresponding secret
  validation and leaves those names out of the rendered environment file, which
  makes the role usable for a Wagtail site that serves static files with
  WhiteNoise and media from local disk and runs without Sentry.

- `voxhelm_deploy` gained `voxhelm_lane_scheduler_interactive_slots` and
  `voxhelm_lane_scheduler_non_interactive_slots` (both default `1`) for
  Voxhelm's bounded inference slots (Voxhelm decision D-24): one reserved
  interactive slot plus one non-interactive slot, rendered into `voxhelm.env`.
- `nyxmon_storage_exporter` can now report per-client Time Machine footprint
  from the server side. `nyxmon_storage_exporter_timemachine_bundle_dirs`
  lists directories to scan for `*.sparsebundle` directories; each bundle is
  exported under `timemachine_bundles_by_name` with `bytes_used`,
  `client_bytes_available`, `last_bytes_to_copy`, `running`, `band_count`,
  `band_size_bytes`, `bands_bytes`, `backup_count`, `oldest_backup_ts`,
  `newest_backup_ts`, `newest_backup_age_days`, `history_days`, `ok`,
  `metrics_known`, and `error`, plus a `timemachine_bundle_scan` summary. The
  probe is read-only (three small plists and a `bands/` entry count; it never
  opens a band or mounts a bundle), a missing or unparsable plist marks only
  that bundle `ok: false`, and bundles on a quiet-hours pool reuse the probe
  cache like datasets.
- Added `daybook_voice_memo_inbox_deploy`, a disabled-first macOS Aqua
  LaunchAgent role for the Daybook Apple Voice Memos importer. It installs an
  exact bundled Daybook commit, keeps source/state/log/credential boundaries
  explicit, rejects placeholder secrets, baselines historical database
  identities only behind a confirmation phrase, and schedules privacy-safe
  ingestion every 300 seconds with `RunAtLoad`. Activation failures are
  rescued to a proven disabled/unloaded state, an unreadable existing
  checkout is never deleted, the bundle is verified to carry the pinned
  commit before any checkout replacement, a modified protected checkout
  fails deployment,
  the scheduled interpreter is staged root-owned and checksum-bound to the
  pinned Homebrew interpreter, fresh-host check-mode guards are keyed by
  path, and empty required values are rejected like placeholders.

- `daybook_voice_memo_inbox_deploy` gained the asynchronous long-memo lane: a
  second disabled-first LaunchAgent
  (`de.wersdoerfer.daybook.voice-memo-inbox-long`) that runs
  `voice-memos transcribe-long --summary-only` every 600 seconds with
  `RunAtLoad` false and its own owner-only `ingest-long` log pair. Deployment
  now quiesces and proves both labels before any managed change, logging the
  aggregate `long_in_flight_count` beforehand instead of waiting for a running
  transcription, and activation enables, bootstraps, and proves the long lane
  with a `transcribe-long --summary-only --no-work` liveness run that accepts
  only `proof_only` (0) or `lock_contended`/`ledger_busy` (75). The rescue path
  disables, boots out, and proves both labels without changing the deployed
  Daybook revision. New `daybook_voice_memo_inbox_long_*` variables are
  rendered into the policy and validated against the reviewed ranges,
  including the deadline inequality
  `ceil(duration x factor) + slack <= 2700`. The lane ships disabled, so the
  short lane's behaviour is unchanged until ops-control enables it after the
  Studio benchmark; enabling requires Voxhelm's bounded inference slots
  (D-24). The long-lane ranges are validated on every run of the role, whether
  or not the lane is enabled, because the values reach the host policy either
  way. Every label-scoped `launchctl print` proof now hides its raw output and
  asserts only the sanitized exit status, so a verbose run no longer prints a
  loaded job's `HOME`, private log paths, and environment; the same applies to
  the Aqua domain probe and to every Daybook CLI invocation (pre-bootstrap
  status, long-lane liveness proof, first-scan wait), whose results and parsed
  reports are hidden while the asserts report only exit status and category,
  enforced by a test; and the pre-quiesce
  in-flight count is extracted best-effort so a malformed status document
  reports nothing instead of aborting the deployment before either label is
  quiesced.

### Changed

- `wagtail_deploy` moved its input validation into `tasks/validate.yml`, like
  the other roles that have one, and `main.yml` imports it. `just test` now
  runs `tests/test_wagtail_deploy.yml` through the new `test-wagtail-deploy`
  recipe; before, that playbook only ever ran when somebody started it by
  hand. The test renders the templates as before and additionally runs the
  validation itself, so an inverted condition on one of the new switches fails
  the suite instead of silently disabling a secret check.

### Fixed

- Attention notifier authorization checks now ignore commented keys and harmless
  field spacing or trailing comments, while rejecting differently authorized
  keys. Attention deployment validates the Daybook wheel name and imports the
  installed module as the service owner before recording installation success,
  without running a tick. Deployment/removal document the persistent launchd
  disable override and the separate explicit enable/bootstrap activation steps.
  Wheel receipts use an explicit destination SHA1; real two-converge tests cover
  unchanged installation and changed wheel bytes without depending on copy return
  fields. Owner import verification starts from the service home and switches
  only its Python subprocess, avoiding inaccessible root SSH working directories.

- `daybook_voice_memo_inbox_deploy` now has a rendered documentation page
  under the deployment roles (the README is included, and the role carries the
  `ops_library_documentation_category` marker so `validate_docs.py` requires
  the page from now on). `tests/test_daybook_voice_memo_inbox_deploy.py` is
  formatted with black; no test changed.
- `macos_time_machine_exclusions` documents that paths under macOS
  privacy-protected locations such as `~/Library/Containers` cannot be managed
  by the launchd-run agent and must receive a one-time sticky exclusion from a
  session with Full Disk Access.
- `echoport_deploy` now provisions and verifies the `mc` alias that the
  `cleanup_old_backups` cron uses as the service user, and exports
  `MINIO_MC_PATH` / `MINIO_ALIAS` to the application environment. The alias
  previously existed only for the root-run upload scripts, so every scheduled
  deletion failed silently and MinIO retention never applied.

### Changed

- `wagtail_deploy` now defaults to Python 3.14.7, keeping its uv-managed
  runtime on the latest 3.14 patch release.
- `openclaw_deploy` can opt its selected audio-provider transport into
  private-network requests for a dedicated local audio route. The provider is
  configurable and defaults to the bundled `senseaudio` media adapter so local
  endpoint credentials stay out of the normal OpenAI agent-auth namespace. Its deploy
  health gate now derives Telegram readiness from complete raw gateway
  overrides as well as the role's individual channel variables. It also keeps
  OpenClaw's internal Doctor backup directory writable by the container
  identity.

### Added

- Added `macos_time_machine_exclusions`, a non-destructive daily LaunchAgent
  that reapplies user-scoped `tmutil` exclusions to configured reproducible
  paths when build directories are recreated, continues through per-path
  failures, tolerates transient launchd bootout races while retrying the
  authoritative bootstrap, reports newly applied exclusions as changes, leaves
  standard macOS directory modes intact, and rejects deployment under the wrong
  user or home.
- `nyxmon_storage_exporter` can now publish named ZFS dataset usage,
  availability, quota, reservation, and snapshot-retained byte metrics for
  stable Nyxmon JSONPaths and proactive dataset-capacity alerts. Parseable
  `zpool` output supplies exact byte fields, while quiet-hours pool, dataset,
  and disk policies avoid HDD wakeups and preserve cached health signals.
  Dataset payloads retain a stable nullable metric schema plus `metrics_known`
  when probes are skipped or fail.
- Added the `local.ops_library.zfs_size_to_bytes` filter for exact ZFS binary
  size normalization. It truncates fractional values the same way ZFS does,
  avoiding one-byte idempotency drift from rounded generic size filters.

### Changed

- **Breaking output-format clarification:** `nyxmon_storage_exporter` now runs
  `zpool list -H -p`, so the existing `pools.<name>.size`, `alloc`, and `free`
  keys contain raw byte strings and `cap` contains a raw percentage number
  string without `%`. Consumers should use the numeric `size_bytes`,
  `alloc_bytes`, `free_bytes`, and `cap_ratio` keys instead; `cap_ratio` is
  calculated from exact allocation and size bytes rather than whole-percent
  `cap` output.

### Fixed

- `nyxmon_deploy` now restricts its SQLite database family to the service
  account and sets `UMask=0077` on both writers, preventing stored JSON-check
  credentials from being exposed through the database or new sidecars.
- `openclaw_deploy` can apply upstream Codex fix `26e5c2858a` to the exact
  `@openclaw/codex@2026.9.1` runtime. The backport gives app-server startup
  process registration a shared ten-second inspection budget, preventing
  synchronous session-snapshot reads from intermittently failing isolated
  heartbeats. The compiled bundle is reconciled atomically with pinned pristine
  and patched digests and fails closed on unknown artifacts.
- `storage_metrics_endpoint` and `thermal_metrics_endpoint` collector timers
  no longer remain `active (elapsed)` with no next run after their one-shot
  boot trigger is consumed and no service-relative trigger remains. Both
  timers now have independent activation-relative and wall-clock anchors, and
  both roles repair and reject an unarmed timer during deployment.
- `zfs_pool_deploy` and `zfs_dataset` now compare exact byte-normalized dataset
  size properties using ZFS's truncating conversion, so both exact values such
  as `quota: 6.5T` and fractional values such as `quota: 1.1T` remain
  idempotent when `zfs get -p` renders integer bytes. Symbolic `auto` is forced
  only for `refreservation`; properties that report `auto` directly remain
  idempotent. Native YAML integers are normalized without regex type errors,
  and the forced symbolic reapply no longer reports a false configuration
  change when it succeeds.
- `nyxmon_storage_exporter` now distinguishes missing quiet-hours SMART evidence
  from an observed disk failure, and distinguishes unavailable EDAC counters
  from observed correctable or uncorrectable errors. This prevents monitoring
  gaps from masquerading as critical hardware failures while keeping real
  failures alertable. Current smartctl failure bits remain critical; signal
  exits and command-launch failure codes remain unknown evidence; and historical
  attribute/error/self-test bits are exported separately.
- `nyxmon_storage_exporter` pool payloads now keep a stable nullable schema and
  separate `health_known` from `health_failed`, so an expired quiet-hours cache
  warns about missing evidence without impersonating a pool failure.
- `nyxmon_storage_exporter` now caches positively observed SMART failures even
  when smartctl also ended abnormally, preserving critical evidence through the
  following quiet-hours window.
- Pool, disk, and dataset payloads now expose stable cache metadata keys on
  active, cached, and uncached-fallback samples, so freshness JSONPaths do not
  disappear when probe state changes.
- Optional pool capacity policies now expose evidence-aware warning/critical
  failure booleans, allowing missing capacity evidence to warn without creating
  a false critical while still evaluating exact ratio and integer free-byte
  thresholds. Policies support both explicit pool lists and pool auto-discovery.
- Disk payloads now also keep `temp_c` present with `null` when no temperature
  evidence is available, including legacy-cache and quiet-hours fallbacks.
- Quiet-hours cache reuse now verifies the configured disk or dataset identity,
  and disk/dataset cache updates share one final write so write-error diagnostics
  describe the actual persisted state.
- `traefik_deploy` now creates its ACME directory as `0700` in the original
  directory loop. Previously every run briefly changed it to `0755` and then
  back to `0700`, producing false idempotency changes and momentarily making
  the private state directory world-traversable.
- `traefik_deploy` no longer exposes Prometheus metrics on `:8080` on every
  interface when the dashboard is disabled. Metrics default to the `traefik`
  entrypoint, and when nothing defined it Traefik created it implicitly on
  `:8080`; a host without a firewall served `/metrics` to the internet after
  its first restart under the role. The entrypoint is now defined explicitly
  and bound to `traefik_metrics_bind_address:traefik_metrics_port` (default
  `127.0.0.1:8080`). Hosts with the dashboard enabled are unchanged.
- `os_apt_maintenance`'s kernel comparison never fired. `_installed_kernel_versions()`
  read a `stdout` key from `run_command()`, which only exposes a 4000-character
  `stdout_tail`, so every host parsed an empty kernel list and the new signal
  silently degraded back to the marker file alone - the same false negative it
  was written to close. The kernel list is now read from the full `dpkg-query`
  output directly, and the unit tests fake `subprocess.run` (the real
  boundary) instead of `run_command()` with a shape it never produced.
- The `os_apt_maintenance` endpoint discarded the persisted kernel signal: it
  replaced `reboot_required` with the live marker-file check on every request,
  so a check asserting `$.reboot_required == false` could never see
  `stale_kernel` even once the run recorded it. The endpoint now serves the
  live marker OR the persisted kernel signal, and drops the kernel signal as
  soon as `uname -r` no longer matches the kernel the run observed, so a reboot
  into the new kernel still clears the warning immediately. It also serves
  `$.reboot_required_details` with the reasons.
- `os_apt_maintenance` no longer reports "no reboot needed" on hosts where
  Ubuntu's `/var/run/reboot-required` marker can never appear. That file comes
  from `update-notifier-common`, which Debian does not ship and which some
  Ubuntu hosts lack, so the check reported a confident green on a Debian 12 host
  that had been running a bullseye `5.10` kernel with `6.1` installed for over
  two years - a false negative indistinguishable from a healthy host. Reboot
  state is now the OR of the marker file and a `dpkg-query`-vs-`uname`
  comparison, and `$.reboot_required_details` reports which signal fired.
  Existing Ubuntu behaviour is unchanged.
- `traefik_deploy`'s conflict disarming no longer fails on a unit that systemd
  references but whose file is gone (a removed `apache2` leaves
  `apache2.service  not-found  failed`). `service_facts` reports such an entry
  identically to a real failed unit, so the role tried to stop it and aborted
  the play with "Could not find the requested service". Unit existence is now
  probed with `LoadState`.

### Fixed

- `nyxmon_deploy` no longer trips `attempt to write a readonly database` during a
  source sync. Both `ansible.posix.synchronize` tasks now pass `owner: false` /
  `group: false`: `synchronize` defaults to `archive: true`, which implies
  `-o -g` and stamped the controller's uid/gid onto the destination directory,
  taking write access away from the service user mid-sync
  (`SQLITE_READONLY_DIRECTORY`, because SQLite must create a journal file
  there). `nyxmon_rsync_excludes` now also covers the `-wal`, `-shm` and
  `-journal` sidecars and `.env`; excluding only `db.sqlite3` still let
  `rsync --delete` remove a live journal out from under the writer.
- `tailscale_metrics_endpoint` timer-arming probes and their assertion are now
  skipped under `--check`. They forced `check_mode: false` while unit rendering
  and startup remained check-mode no-ops, so a first deployment under `--check`
  queried a nonexistent timer and failed.

### Added

- `openclaw_deploy` can now route voice notes to an OpenAI-compatible local
  transcription endpoint through a dedicated, explicitly selected API-key
  profile. The role stores only an environment SecretRef in OpenClaw's SQLite
  auth store, preserves explicitly non-audio media models, and prevents normal
  OAuth-backed agent turns from inheriting the transcription credential.
- `openclaw_deploy` now migrates the pre-2026.9.1 memory-search and timestamp
  config keys before plugin reconciliation, so in-place upgrades do not fail
  the newer schema validation.
- `openclaw_deploy` now detects and safely migrates v2026.9.1 legacy workspace
  state through upstream non-interactive Doctor repair before startup, then
  verifies gateway RPC and Telegram readiness instead of accepting a briefly
  open port from a crash-looping container.

- `tailscale_metrics_endpoint` can now inspect `/proc/mdstat`, report each
  active array (including `active (auto-read-only)` arrays) and its `[UU]`-style
  member bitmap, require an explicit set of array names, and include required
  mdraid health in `summary.overall_ok`. This closes the monitoring gap that
  left a degraded staging `/boot` mirror unnoticed for more than three years.
  Active bitmap-less RAID0/linear arrays are supported, and disabled probes
  report an unknown value instead of an unevaluated healthy value.
- `traefik_deploy` now stops, disables and masks stock distro web-server units
  (`nginx.service`, `apache2.service`, `caddy.service`, `lighttpd.service`)
  before starting Traefik, controlled by
  `traefik_mask_conflicting_web_services` / `traefik_conflicting_web_services`.
  Installing nginx - which several roles pull in as a dependency for their own
  sidecar instance - enables a stock unit that binds `:80`; nothing disabled it,
  so it raced Traefik for the port on every boot and could take a host's entire
  ingress down. Masking rather than disabling is deliberate, because `apt
  upgrade` re-enables a disabled unit and would silently re-arm the trap on
  hosts running unattended apt maintenance. Only units already present are
  touched, and sidecar units (`mastodon-nginx`, `takahe-nginx`) are unaffected.
  The tasks are also includable standalone via `tasks_from: web_conflicts`, for
  hosts whose Traefik this role does not manage.
- `netplan_config` can now install an optional networkd route guard that
  reconfigures a carrier-up interface when its IPv4 default route disappears or
  its setup state becomes failed. Managed `netplan generate`, `netplan apply`,
  and follow-up `networkctl reconfigure` commands share the guard lock so
  recovery commands cannot execute concurrently with those planned transitions.
- `tailscale_metrics_endpoint` now reports `Self.Online` and an optional IPv4
  default-route probe, with a configurable systemd IP allow-list for authenticated
  LAN-side monitoring when the Tailscale path itself is broken. Existing
  `summary.overall_ok` behavior stays compatible unless the new
  `tailscale_metrics_endpoint_require_self_online` or
  `tailscale_metrics_endpoint_require_default_ipv4_route` option is enabled;
  route-probe errors count as an unhealthy required route. Allow-list validation
  parses real IP networks and rejects prefixes broader than `/8` for IPv4 or
  `/32` for IPv6, as well as out-of-range prefixes. Deployments now fail closed
  unless `bpftool` confirms systemd attached both cgroup ingress and egress IP
  filters to the endpoint service when fail-closed verification is enabled;
  Ubuntu deployments install the GA-tracking `linux-tools-generic` metapackage
  so verification survives GA kernel upgrades; HWE hosts must separately retain
  their release-specific HWE tools metapackage. Use the option for non-Tailnet
  binds. The collector unit also gains a new
  address-family sandbox permitting only `AF_UNIX`, `AF_INET`, `AF_INET6`, and
  `AF_NETLINK` (needed by the route probe).
- `nyxmon_deploy` now renders consecutive-failure, persistent-reminder,
  stale-processing-lease, and bounded check-batch settings into Nyxmon's worker
  environment.
- `os_apt_maintenance` gained executable coverage for the failed-run state-file
  repair (`just test-os-apt-maintenance-failed-run`): the molecule scenario
  points the role at an `apt-get` stub that exits 100, resets `state.json` to
  the pre-fix `0600 root:root`, and asserts the file comes back
  `root:<endpoint group> 0640` both through systemd and when the writer runs
  outside systemd, with the endpoint answering HTTP 200 and `last_run_ok=false`
  rather than 503.
- `tailscale_metrics_endpoint` gained a molecule scenario
  (`just test-tailscale-metrics-timer`) that reproduces a parked
  `active (elapsed)` collector timer against real systemd, asserts the
  deployment fails rather than accepting it, and asserts the role re-arms it
  once it can. The scenario also watches the payload file actually get a newer
  mtime, so "armed" is proven by the collector running rather than by the unit
  file.

- `mail_backend_deploy` gained `mail_backend_sender_only_domains`: domains the
  backend signs and authorises as an envelope sender, but hosts no mailboxes for.

  The motivating case is an application on another host that submits through this
  backend with a `From:` in its own service subdomain — Mastodon sending as
  `notifications@fedi.wersdoerfer.de`, Takahe as `noreply@fedi.python-podcast.de`.
  Neither can rewrite its envelope sender, and submission enforces
  `reject_sender_login_mismatch`, so each address needs an `alias` row pointing at
  the submission mailbox. `alias.domain` is a foreign key onto `domain.domain`, so
  the domain has to exist before the alias can — but adding it to
  `mail_backend_domains` would make it a hosted domain, put it into
  `virtual_mailbox_domains`, and generate `postmaster@`/`abuse@` aliases pointing at
  a mailbox that does not exist.

  A sender-only domain gets exactly two things instead: a DKIM keypair with matching
  `signing.table` and `key.table` entries, and a `domain` row with `active = '0'`.
  The inactive flag is the whole trick — `virtual_domains.cf` filters on
  `active = '1'`, so Postfix never treats the domain as local while the foreign key
  is still satisfied. The insert is `ON CONFLICT DO NOTHING` and an overlap with
  `mail_backend_domains` is rejected up front, so an already-hosted domain can never
  be demoted to inactive by task ordering. The converse is checked too: `DO NOTHING`
  would otherwise let a pre-existing *active* row silently defeat the sender-only
  guarantee, so the role reads the row back and fails rather than proceeding with a
  domain that Postfix still treats as local. `alias_domain` rows get the same
  treatment, both as configured and as they exist in the database:
  `virtual_domain_aliases.cf` resolves recipients through `alias_domain` without
  consulting `domain.active`, and the role never deletes those rows, so a stale one
  would keep the domain accepting mail no matter what the flag says. Entries must be
  lowercase, because
  `alias.domain` is written lowercased against a case-sensitive foreign key and a
  mixed-case entry would pass every case-insensitive existence check before failing
  at alias insert time.

  Sender-only domains are deliberately not added to `trusted.hosts`. That file is
  OpenDKIM's `InternalHosts` list and matches the connecting client, not the sender
  domain; signing happens because the submission session is SMTP authenticated,
  which OpenDKIM already treats as origination. This was confirmed against the
  running host rather than assumed — mail relayed in from the edge host on port 25
  logs `not internal` / `not authenticated` and goes unsigned, while locally
  submitted mail is signed.

  PostfixAdmin schema mode only; legacy mode has no equivalent and the role fails
  rather than silently doing nothing.

- `mail_users_sync` gained a per-user `send_as` list, which writes the alias rows
  that authorise a login to use other addresses as envelope sender. This is the
  consumer side of `mail_backend_sender_only_domains`.

  An `alias` row is also read by `virtual_alias_maps`, so a careless entry could
  reroute somebody's incoming mail. Four things are therefore checked before any row
  is written: PostfixAdmin mode, address shape, no address claimed by two users, and
  no collision with an address the role already manages for a mailbox (its own
  address, or its localpart on a `mail_users_additional_alias_domains` domain). The
  send-as domain must already exist in the `domain` table, and the failure message
  names `mail_backend_sender_only_domains` so the fix is obvious.

  Those checks only see `mail_users_list`, so the database is checked as well: an
  entry whose address already exists in `alias` pointing at something else is
  refused outright. That is what catches the rows this role never created —
  `postmaster@`/`abuse@` from `mail_backend_deploy`, a mailbox self-alias, or a
  leftover from a user dropped from the secrets file. Taking one of those over would
  reroute real incoming mail *and* grant its sender identity to the new login, which
  is too much to do as a side effect of `ON CONFLICT DO UPDATE`.

  Both database checks run ahead of the per-user sync loop rather than inside it.
  They can only fail on operator error, and failing halfway through the loop would
  leave earlier users written while a later user's `send_as` was still unvalidated.

  Removing an entry does not delete the alias row; revoking an authorisation for
  real is a manual `DELETE`. This matches how the role already treats alias-domain
  rows.

- `paperless_deploy` can now blacklist dates that must never be taken as a
  document's creation date, via `paperless_ignore_dates`. `PAPERLESS_IGNORE_DATES`
  was previously hardcoded empty in the template with no way to set it.

  This addresses a real ingestion failure: a scanned medical form whose printed
  date OCR'd to garbage fell through to the date of birth printed on the same
  form, so the document was filed decades in the past. The document list sorts
  by date descending, so it landed last of several hundred documents and looked
  like it had never been ingested — the pipeline itself was healthy throughout.
  Ignoring the date of birth makes Paperless fall back to the file's mtime, i.e.
  the scan date.

  The date order used to read dates out of document *content* is now
  `paperless_date_order` instead of a hardcoded `DMY`, so the two settings can be
  kept consistent. The default is unchanged.

  Entries are parsed by `dateparser` using `paperless_date_order`, and an ISO
  `1970-02-01` string does **not** parse under `DMY` — dateparser returns None
  and the entry is dropped silently, leaving the setting looking applied while
  ignoring nothing. `validate.yml` now rejects ISO-formatted entries under a
  non-YMD order rather than allowing that silent no-op, and also constrains
  `paperless_date_order` to `DMY`/`MDY`/`YMD`.

### Changed

- `nyxmon_deploy` replaces sample-count alert reminders with elapsed-time ones.
  `nyxmon_notify_repeat_failures` is gone and `NYXMON_NOTIFY_REPEAT_FAILURES` is
  no longer rendered; the role now renders
  `NYXMON_NOTIFY_REPEAT_INTERVAL_SECONDS` from
  `nyxmon_notify_repeat_interval_seconds` (default `21600`) and
  `NYXMON_NOTIFY_WARNING_REPEAT_INTERVAL_SECONDS` from
  `nyxmon_notify_warning_repeat_interval_seconds` (default `86400`). A sample
  count meant a different wall-clock cadence for every check interval — twelve
  samples is roughly hourly for a five-minute check and roughly twelve-hourly
  for an hourly one — which is why it cannot be translated into a duration and
  is ignored rather than converted. Setting the old variable is not an error:
  the role logs a deprecation notice naming both replacements and continues, so
  an inventory can be migrated without a failed deploy.

  `nyxmon_notify_consecutive_failures` now defaults to `2` instead of `1`. A
  first-sample page for every check is what turned one wedged batch into an
  alert storm; hosts that genuinely need first-sample paging set it per check
  rather than globally. All five reliability settings are now validated as whole
  numbers first and then range-checked (threshold 1..100, reminder intervals
  60..2592000 seconds), so a typo fails the deploy instead of silently landing
  in the worker environment.

- `certbot_dns_deploy` renewal-hook items now run in isolated fail-fast blocks;
  all independent items are attempted and failures are identified and
  propagated. Existing ordering-dependent hook lists must combine prerequisite
  commands into one multi-line item; an `exit`-based lineage guard must be in the
  same item as every command it gates. Downstream inventories must migrate their
  effective lists in the same rollout.

- `takahe_deploy` lets an operator turn Django error mail off. The role used to
  assert that `takahe_error_emails` was non-empty, so "no error mail" was not a
  configuration you could express; the only way to stop the mail was to point it
  at an address you did not read.

  An empty list is now an explicitly supported value meaning *do not send error
  mail*, and the rendered `.env` says so. Takahe assigns `ADMINS` only when
  `TAKAHE_ERROR_EMAILS` parses to a non-empty list, and Django's `mail_admins()`
  is a no-op with empty `ADMINS`, so nothing is sent and nothing is queued.

  The template keeps writing the key as `TAKAHE_ERROR_EMAILS=[]` instead of
  omitting it, because the two candidate "off" spellings are not equivalent.
  Takahe declares `ERROR_EMAILS: list[EmailStr] | None` in a pydantic v1
  settings model, and pydantic parses a complex field's environment value as
  JSON: an absent variable and `[]` both leave error mail off, but an empty
  string raises `SettingsError` and the service never starts. This was verified
  against the pydantic 1.10.17 install on the production host rather than
  inferred. Validation was tightened to match — a bare string, including
  `CHANGEME` and the empty string, is now rejected with a message that names the
  supported forms, so a wrong value fails during the play instead of after the
  restart.

  This matters for `fedi.python-podcast.de`, a two-user instance whose entire
  outbound mail volume is `502 Bad Gateway` reports from
  `/proxy/post_attachment/...`. Takahe returns 502 there whenever the remote
  instance holding an attachment is unreachable, which on the fediverse is
  routine rather than a defect, so the reports carried no signal while consuming
  a metered mail quota.

- `mailgun_relay_deploy` pins where the relay's log output goes and labels it.
  The unit now sets `StandardOutput=journal`, `StandardError=journal` and
  `SyslogIdentifier=mailgun-relay` instead of inheriting the system defaults and
  showing up in the journal as an anonymous `python[<pid>]` alongside every
  other python unit on the host. `journalctl -t mailgun-relay` now works.

  This came out of an investigation that concluded the relay "logs nothing to
  journald" and blamed a block-buffered stdout pipe with no `PYTHONUNBUFFERED`.
  That diagnosis is wrong: `logging.StreamHandler.emit` flushes the stream after
  every record, so the relay's lines reach the journal as they are emitted. The
  observed silence on macmini was journald retention (the unit started before
  the oldest retained entry) plus no mail traffic in the retained window; a
  probe request produced its access-log line in the journal immediately. The
  unit carries a comment saying so, and the role README now documents how to
  tell an idle relay from a broken one, so the placebo does not get added later.

- Paperless-ngx 2.20.15 -> 3.0.4 and PostfixAdmin 3.3.13 -> 4.0.5, the two major
  upgrades deferred from the previous pass. Neither is a version bump alone.

  Paperless v3 requires 2.20.15 exactly as the upgrade source, which is what was
  pinned, so the direct jump is supported. Three v3 migration items applied to
  this deployment. `PAPERLESS_OCR_MODE=skip` no longer exists — v3 decoupled OCR
  from archive-file generation and the upstream mapping table sends the old
  `skip` to `auto`, so `paperless_ocr_mode` now defaults to `auto`. The
  individual advanced database variables were replaced by a single
  `PAPERLESS_DB_OPTIONS`, so the template emits that instead of
  `PAPERLESS_DBSSLMODE`, fed by the new `paperless_db_options`. And v3 needs to
  be told which proxy to trust or logins can fail with 403, so the template now
  emits `PAPERLESS_TRUSTED_PROXIES`, defaulting to loopback because Traefik
  fronts it there.

  The rest of the v3 breaking changes were checked against the live
  configuration and do not apply: no encryption passphrase (v3 removed document
  encryption and would have required decrypting first), no pre/post-consume
  scripts, no consumer polling or barcode-scanner settings, and
  `PAPERLESS_SECRET_KEY` was already set — v3 makes it mandatory. Note that v3
  drops task history, rebuilds the search index from Whoosh to Tantivy on first
  start, and no longer rejects duplicate documents by default.

  PostfixAdmin 4.0 changed how the software has to be fetched, not just its
  version. Tags went from `postfixadmin-3.3.13` to `v4.0.5`, so the old URL would
  404, and 4.0 needs composer dependencies the GitHub source archive does not
  ship — it aborts on a missing `vendor/autoload.php`. The download now points at
  upstream's self-contained release asset. Of the two builds published per
  release, `php84` carries the updated spomky-labs/otphp with the two CVEs fixed
  in 4.0.4 while `php74` does not, and nothing in the php84 vendor tree requires
  more than PHP 8.1, so `postfixadmin_release_build` defaults to `php84`. The
  download is now checksum-verified, which it was not before. 4.0 drops PHP 7.4
  through 8.1 and removes the MySQL ENCRYPT hashing backend; neither bites here
  (PHP 8.3, PostgreSQL). Schema changes are handled by the existing idempotent
  `upgrade.php` step.

### Fixed

- `os_apt_maintenance`: a failed apt run left the monitoring endpoint answering
  HTTP 503 until the next successful run. The script writes `state.json` via
  `tempfile.mkstemp` (0600, root) and `os.replace`, and the unit widened it back
  to `root:<endpoint group> 0640` in `ExecStartPost=` — which systemd skips
  entirely when `ExecStart=` exits non-zero. The endpoint user could then not
  read the file, so a truthful `last_run_ok: false` / `reboot_required: true`
  state was replaced by a generic 503. `atomic_write_json` now stamps the final
  group and mode onto the open temp file descriptor before `os.replace` (best
  effort; a permission problem there never aborts the run), and the unit's
  fix-up moved from `ExecStartPost=` to `ExecStopPost=-`, which runs on success
  and failure alike. The `ExecStartPre=` directory hooks are unchanged.
- `tailscale_metrics_endpoint`: the collector timer could park permanently and
  freeze the served payload. `OnBootSec=` and `OnUnitActiveSec=` are both
  monotonic; after the one-shot boot trigger fired, missing service activation
  history could leave neither with a next elapse, and systemd left the timer
  `active (elapsed)` with
  `NextElapseUSecMonotonic=infinity`. `Persistent=true` did not help because it
  only applies to `OnCalendar=`. The endpoint kept serving the frozen snapshot,
  so every `summary` assertion built on it stayed green while the host was
  unmonitored. The timer template now also sets `OnActiveSec=` (anchored on the
  timer unit's own activation) and `OnCalendar=` (new variable
  `tailscale_metrics_endpoint_timer_on_calendar`, default `*:0/5`). Because
  `systemd: state: started` is a no-op on an already-active timer and could not
  repair this, the role now reads the timer's `NextElapseUSecMonotonic` and
  `NextElapseUSecRealtime`, restarts a timer that has no future trigger, and
  asserts the timer is armed afterwards.

- `nyxmon_deploy`: a deploy could make the running collector fail with
  `sqlite3.OperationalError: attempt to write a readonly database`. The source
  sync ran with rsync's archive defaults, which stamp the controller's uid/gid
  onto the *destination directory itself*. With `journal_mode=delete` SQLite has
  to create `db.sqlite3-journal` next to the database for every write
  transaction, so losing write permission on that directory is
  `SQLITE_READONLY_DIRECTORY` — reported with exactly that message. The window
  closed a few seconds later when the role's recursive `chown` ran, which is why
  it showed up as a single failed collector iteration mid-deploy.

  The sync now passes `owner: false` / `group: false` so it never re-owns the
  destination, and the excludes moved into `nyxmon_rsync_excludes` /
  `nyxmon_rsync_django_excludes`. The previous list excluded only `db.sqlite3`,
  so `rsync --delete` was free to remove a live `-wal`, `-shm`, or `-journal`
  sidecar — losing crash atomicity rather than merely failing a write. It now
  excludes each sidecar by name plus `db.sqlite3*` and `*.sqlite3`, and `.env`,
  which was previously deleted and recreated on every deploy so a restart landing
  in that window would fail to start. The recursive ownership fix still walks the
  in-tree database, which is safe: it only sets owner/group to the service user
  the file already belongs to and never touches modes.

- Corrected the Certbot DNS hook examples and Traefik file-provider guidance:
  rotating a certificate behind `/etc/letsencrypt/live/` does not change
  Traefik's watched dynamic configuration. The examples now restart Traefik and
  reload the active Ubuntu Postfix instance; inventories must adopt those
  commands for the deployed hook to change.

- `openclaw_deploy`: the `/homeassistant` command skill could act on the wrong device
  and report success under the name the user asked for. Asked to switch a device
  outside the write allowlist, the agent discovered the writable domain instead,
  switched the closest-sounding entity there, and confirmed using the original name.
  Observed in production: *"Mach bitte das Amaran-Licht an."* → `turn_on
  light.strahler_tripod` → *"Das Amaran-Licht ist an."*, while the actual target
  (`switch.wintergarten_amaran_60x_s_power`) stayed off.

  The handler's allowlist was working as designed — it blocks the wrong *write*, not
  the wrong *target*. `homeassistant-skill.md.j2` now forbids entity substitution,
  requires naming the entity actually acted on, requires reporting `access denied`
  verbatim instead of retrying against another entity, and forbids treating
  `Changed states reported: 0` as a confirmation. Candidate discovery is no longer
  hardcoded to `--domain light`, which is what steered the agent toward the writable
  domain in the first place.

  A second rule was added after the first fix was verified in production: the agent had
  stopped substituting, but still answered *"das Amaran-Licht ist in Home Assistant
  nicht vorhanden"* after searching only `--domain light`. The device exists as
  `switch.wintergarten_amaran_60x_s_power`; German names a smart plug driving a lamp a
  *Licht* regardless of its HA domain, so words in the request are not domain hints.
  Claiming absence now requires an unfiltered `list` in the same turn.

### Changed

- Bumped pinned upstream versions across the collection: Traefik 3.5.3 -> 3.7.9,
  Navidrome 0.58.5 -> 0.63.2, sops 3.8.1 -> 3.13.3, age 1.1.1 -> 1.3.1, Neovim
  0.11.6 -> 0.12.4, lazygit 0.59.0 -> 0.63.1, nvm v0.39.7 -> v0.40.6, and the
  Python interpreter pins for `homeassistant_deploy`, `wagtail_deploy`,
  `voxhelm_deploy`, and `voxhelm_remote_worker_deploy` to 3.14.6.

  `navidrome_checksums` was updated in the same change as `navidrome_version` —
  the map is keyed by architecture but not by version, so a version bump alone
  would fail the download against the previous release's SHA256. The comment
  above it now says so. Traefik's own `traefik_checksum` default is empty, but
  ops-control pins a bare checksum for `heis` that rides on this role's
  `traefik_version`; that is updated alongside.

  Traefik 3.6/3.7 breaking changes were reviewed: the Kubernetes Gateway API and
  CRD changes do not apply here (file provider only). Of the rest, HTTP/1 CONNECT
  now returns 501, `basicAuth` with an empty users list makes the router 404
  rather than 401, and StripPrefix rejects requests whose normalized path differs
  from the stripped path. Every `basicAuth` middleware in this collection is
  rendered inside an `enabled` guard, so none can produce an empty users list.

- `navidrome_deploy` now renders `EnableSharing` explicitly, defaulting to
  `false` via the new `navidrome_enable_sharing` variable. Navidrome 0.63.0
  flipped the upstream default to `true`, so upgrading without this would have
  silently started handing out public share links on a service that is otherwise
  reachable only behind basic auth. Note that 0.60.0 also made `go-taglib` the
  default metadata extractor, which triggers a full library rescan on first
  start; `Scanner.Extractor` can be set back to `legacy-taglib` if that misreads
  tags.

### Fixed

- `mastodon_deploy` now actually applies `mastodon_nvm_version`. The nvm checkout
  used `ansible.builtin.git` with `update: false`, which pins the requested
  version only on the initial clone — on a host that already had nvm, changing
  the variable reported no change and silently kept the old tag. Bumping the pin
  to v0.40.6 and deploying left staging on v0.39.7, with the play reporting
  `failed=0`. The checkout now runs with `update: true`, so the pinned tag is
  what is on disk after every run. A version pin that quietly does nothing is
  worse than no pin, because the inventory reports a version the host is not
  running.

### Removed

- `nyxmon_deploy` no longer declares `nyxmon_node_version`. It was set to `20`
  and described as "if frontend build is needed", but nothing in the collection
  or in ops-control ever read it — the role does not install Node at all. It
  surfaced as an end-of-life finding (Node 20 went EOL 2026-04-30) for a runtime
  that is never provisioned, so the fix is deletion rather than a bump.

### Added

- New `systemd_unit_masks` role: masks systemd units that can never succeed on a
  host (a driver init script with no matching hardware, a service for an absent
  device) and clears any `failed` state they left behind. Masking a unit that has
  already failed does **not** reset it, so without the reset a permanently
  non-empty `systemctl --failed` hides genuinely new failures. Units are stopped
  before masking, because masking a running unit leaves it running and systemd
  then refuses to act on it. Unit names must include the type suffix — a bare
  name silently resolves to `<name>.service`, which makes it easy to mask
  something other than intended — and a unit listed for both masking and
  unmasking is rejected rather than resolved by ordering. The failed-state reset
  is conditional on `systemctl is-failed`, so repeat runs report no change.

### Fixed

- `ssh_forwarding_identity` now keeps the exact original null-identity creation intent
  authoritative when restarting an absent-companion creation. It reattests that binding and
  both canonical/staging names before allocation, after allocation durability, after binding,
  after canonical publication, and through every intent-retirement fsync. Check mode repeats
  the same absent-companion attestation immediately before returning its snapshot-only plan;
  canonical or staging creation/substitution at any boundary is preserved and fails closed.
- `ssh_forwarding_identity` creation reconciliation now treats a null-identity intent as
  authority only when both its canonical and named staging private-key entries are absent.
  Canonical-only, staging-only, and same- or different-content dual-entry snapshots are
  preserved unchanged and fail closed in check and real mode without key derivation or
  public-key publication.
- `ssh_forwarding_identity` now separates crash-recovery inspection from mutation so
  present-state check mode can validate a recoverable creation intent/staging key and derive
  its prospective public key without any rename, exchange, quarantine, intent persistence,
  or directory fsync. Authenticated cleanup keeps descriptor authority for the quarantined
  inode and requires the original private, public, or creation-intent canonical name to stay
  absent immediately after exclusive rename and after every retirement fsync; concurrent
  recreations are preserved and fail closed.
- `ssh_forwarding_identity` now retains public-key and creation-intent publication
  descriptors and exact bytes through old-name retirement, then reattests the canonical
  inode, descriptor identity, and bytes after cleanup's final directory fsync. Creation
  reconciliation carries the original exact `RegularBinding` through every update and
  clear; updates return the replacement binding, and no transition fresh-reads a different
  valid intent as authority. Canonical substitution immediately before update or clear,
  and public-key/intent substitution during retirement cleanup, are preserved fail closed.
- `ssh_forwarding_identity` absent-state cleanup now carries the full inode identity returned
  with each exact validated private/public byte sequence into quarantine cleanup. It never
  authorizes removal from a fresh pathname stat, so substitution between read and cleanup is
  preserved and rejected.
- `ssh_forwarding_identity` cleanup/removal now pins the exact validated inode across a
  descriptor-relative exclusive source-to-quarantine transition, fsyncs, and reattests the
  moved descriptor/path identity including durable `st_ctime_ns` records. A precreated
  target or post-verification source swap fails closed; because no portable exact-handle
  unlink is available, authenticated quarantines are retained instead of risking
  verify-then-pathname-unlink.
- `ssh_forwarding_identity` now inspects canonical private/public keys, creation intent,
  and recovery staging state only through nonblocking, close-on-exec, no-follow descriptors,
  with immediate regular/single-link/owner/mode and stable descriptor/path identity checks.
  FIFOs, sockets, devices, directories, hard links, and replacements fail promptly. Private
  key and creation-intent publication now use descriptor-relative exclusive rename rather
  than hard links, eliminating link-count-two crash states while preserving exclusive,
  non-rotating restart recovery.
- `ssh_forwarding_identity` now creates a first private key through a random
  descriptor-relative staging name and durable owner-only creation intent. It uses an
  EINTR-aware write-all loop, rejects zero progress, fsyncs and read-verifies the complete
  key, re-derives Ed25519 public material, binds the exact staging inode, and installs the
  canonical name exclusively before parent-directory fsync. Restart completes only a
  bound, content-verified staging inode; an unbound or replaced temporary and any partial
  canonical key are preserved fail closed. Controlled partial/zero/`ENOSPC` failures clean
  only the exact attested temporary, while existing canonical keys remain non-rotating.
- `ssh_restricted_forwarding_account` now records a root-only UID/GID identity
  contract and attests exact passwd, primary-group, shell, canonical home, ownership,
  and no-follow hierarchy state before absent-state policy or account mutation. Partial
  removal resumes reject recycled UID/GID names, always scan the contracted UID, and fail
  closed on unreadable process state until home and contract are gone. Linux `statx` mount
  IDs now pin `/home` before accepting the managed home, so bind/tmpfs filesystems mounted
  directly at the canonical home are refused and preserved alongside same-device bind mounts,
  tmpfs, and other nested filesystems. The IDs now preflight the complete tree under the
  stable absent transaction lock before sshd policy, authorization, passwd, contract, home,
  or content mutation, and are rechecked during traversal. Actual absent-transaction
  Molecule cases prove direct and nested mounts preserve every managed remnant. Real absent
  runs retain mandatory contracted-UID process scanning; read-only check mode reports
  active restricted sshd processes as a deferred post-shutdown gate because it intentionally
  does not boot out the healthy client. The role removes accounts without recursive
  `userdel` and descriptor-removes only the pinned canonical managed home, preserving
  drifted or repurposed accounts and unrelated data.
- `vaultwarden_deploy` no longer renders a separate Traefik WebSocket router and
  service pointing at `WEBSOCKET_PORT`. Upstream Vaultwarden removed the
  standalone WebSocket listener and serves live sync at `/notifications/hub` on
  the main Rocket port, so that router pointed at a port nothing listened on —
  and because its rule was longer than the main router's, it won on priority and
  answered `502` for every live-sync request. `WEBSOCKET_ADDRESS` and
  `WEBSOCKET_PORT` are gone from the env template and
  `vaultwarden_websocket_port` from the defaults; `vaultwarden_websocket_enabled`
  remains and still gates `WEBSOCKET_ENABLED`.

### Added

- Added `ssh_forwarding_identity` and `ssh_restricted_forwarding_account` for
  unattended, non-rotating Ed25519 forwarding identities and dedicated Linux
  accounts constrained to one local-forward destination. The server role uses
  restricted authorized-key options plus a validated sshd `Match User` block,
  validates candidate policy before mutation, accepts only canonical managed-file
  pre-state, and restores managed bytes, absence state, and canonical metadata after
  failed validation or reload. Rollback activation now requires a successful restored
  reload plus matching effective-policy attestation; timestamps, ACLs, and xattrs are
  explicitly outside rollback semantics. Present and absent account operations now
  share a non-expiring, explicitly authenticated server transaction holder, a durable
  unreleased marker that survives holder death, and monotonic fencing state that rejects
  obsolete workflows before mutation/finalization. The account-derived root-only recovery
  credential is now file- and directory-fsynced before marker publication, survives `/tmp`
  loss/reboot, remains recoverable across every takeover power-loss boundary, and is removed
  durably with the marker after authenticated release. Stale recovery authenticates that
  stable credential, attests holder death, and advances fencing. Candidate sshd
  construction rejects source symlinks and mutates only descriptor-attested temporary-tree
  targets. Identity
  management traverses every component from `/` through pinned `O_NOFOLLOW|O_DIRECTORY`
  descriptors and keeps parent creation plus key writes descriptor-relative, preventing
  ancestor/parent symlink substitution from redirecting mutation. It never manages root
  authorized keys.
- New `vaultwarden_maintenance` role: an ingress deny switch for a maintenance
  window. `vaultwarden_maintenance_state: present` writes a high-priority
  Traefik router fronted by an `ipAllowList` middleware, so sources outside the
  allow list get `403` while allowed sources still reach Vaultwarden — which is
  what gives an operator a verification path during a freeze. `absent` removes
  the file; Traefik watches the dynamic directory, so no restart is needed. One
  router covers live sync too, since Vaultwarden serves it on the main port.
  The role owns **only** the file named by `vaultwarden_maintenance_filename`
  and refuses to run if that name equals
  `vaultwarden_maintenance_archived_router_filename`. Both are plain filenames,
  never paths, so no caller value can normalise into the archived router file.
  That guard is load-bearing: the Echoport Vaultwarden backup archives the deploy role's
  router file and its restore writes it back without reloading Traefik while
  gating only on a loopback health check, so a deny state stored there would be
  silently reinstated by any restore from a backup taken during a freeze. Every
  run verifies the result — no non-loopback listener on the Vaultwarden ports,
  plus an external probe expecting `403` while frozen and a reachable status once
  restored. The role deliberately contains no package, repository, or service
  tasks and defines no handlers.
- `vaultwarden_deploy` can now pin and hold its packages:
  `vaultwarden_package_version`, `vaultwarden_web_vault_package_version`, and
  `vaultwarden_packages_hold`. Versions default to empty and the hold defaults
  to unmanaged (`~`), so existing behaviour is unchanged and an externally
  applied hold survives an ordinary deploy run untouched. Both versions must be pinned
  together or not at all, because the apt flag that permits moving a held
  package applies to the whole invocation. When pinned, apt is permitted to move
  the held packages directly rather than the
  role unholding and re-holding around the install: there is no window for a
  concurrent apt process, no spurious change report when the pinned version is
  already installed, and no check-mode failure from simulating an install
  against a still-held package. Because the hold itself can only be applied
  after the install, the role then reads the installed versions back and fails
  if they are not the requested pins. The role also reports the
  installed deb versions, which is the value a compatibility or migration gate
  has to record per host.

- `voxhelm_deploy` gained an optional Kokoro ONNX TTS backend and automatic
  de/en language routing, both disabled by default and independently toggleable
  (`voxhelm_tts_kokoro_enabled`, `voxhelm_tts_language_routing_enabled`, both
  `false`). Enabling Kokoro installs `espeak-ng` via Homebrew and downloads the
  checksum-pinned model artifacts (`voxhelm_kokoro_artifacts`: official Kokoro
  v1.0 full + int8, `voices-v1.0.bin`, and the German "Martin" fine-tune) into
  `voxhelm_kokoro_model_dir` with idempotent, `sha256`-verified `get_url`
  downloads. The single enable flag gates BOTH the `kokoro` uv extra and Kokoro
  model registration: when `false`, the env template renders no `VOXHELM_KOKORO_*`
  variables, so Kokoro voices are neither advertised nor dispatchable.
  `voxhelm_kokoro_models` (voice-key → `model_file`/`voicepack_file`/
  `voicepack_key`/`phoneme_language`) renders into `VOXHELM_KOKORO_MODELS`, with
  optional `voxhelm_kokoro_default_voice` and `voxhelm_espeak_library`
  (default `/opt/homebrew/lib/libespeak-ng.dylib`). Routing gates the `routing`
  uv extra and renders `VOXHELM_TTS_LANGUAGE_ROUTING` /
  `VOXHELM_TTS_LANGUAGE_VOICES` (`voxhelm_tts_language_voices`). `validate.yml`
  asserts models are configured and complete when Kokoro is enabled, referenced
  files are provisioned as artifacts, a set default voice is a configured key,
  and a language mapped to a `kokoro-*` voice cannot diverge from Kokoro
  enablement.

- Added `daybook_photos_offload_deploy`, a quiesce-first macOS Aqua user
  LaunchAgent for the pinned, clean-checkout Daybook Photos discovery
  reconciler. It owns private runtime state and owner-only private logs, emits
  aggregate-only scheduled output, uses a root-owned exact checkout plus a
  checkout-local sanitized uv environment, rejects unsafe Git state and path
  substitutions, supports an exact-pin isolated controller Git bundle for
  private source, installs locked dependencies without editable source writes,
  uses a login-style macOS service-user transition, fails closed during
  activation, and runs at 08:10 and 20:10
  without mounting Fractal or mutating Photos.

- `homeassistant_deploy` gained an optional Custom Conversation bridge
  (`homeassistant_custom_conversation_enabled`, default `false`). It installs the
  pinned, checksum-verified `michelle-avery/custom-conversation` component
  (v1.6.1) into `custom_components/`, restarts Home Assistant before running the
  config flow, and provisions the `custom_conversation` config entry idempotently
  against an OpenAI-compatible Chat Completions endpoint (new vars:
  `_version`, `_sha256`, `_provider`, `_base_url`, `_api_key`, `_model`,
  `_instructions`, `_request_timeout`, `_canary_text`). The role owns the domain:
  zero entries → create, one → update data/options in place (base-URL and token
  changes included), more than one → hard fail; disabling removes the entry and
  its stored token. Every token-carrying task runs with `no_log: true`. The
  resolved `conversation.*` entity is gated on registry presence, a
  non-`unavailable` state, and a `conversation/process` canary, and Assist
  pipelines can reference it through the new
  `conversation_engine: "auto:custom_conversation"` token (falling back to
  `conversation.home_assistant` with a warning when the bridge is disabled).
  Provisioning is fully desired-state: clearing
  `homeassistant_custom_conversation_instructions` back to `""` restores the
  component's default prompt (and stays idempotent afterwards), and create,
  update, and remove of the config entry are reflected in the task's Ansible
  changed status. The component validates credentials with a best-effort
  `GET <base_url>/models`, so a Chat-Completions-only endpoint that does not
  serve `/models` (e.g. the OpenClaw gateway) works without a compatibility
  proxy.

- `openclaw_deploy` gained `openclaw_gateway_http_chat_completions_enabled`
  (default `false`) to toggle the gateway's OpenAI-compatible Chat Completions
  endpoint (`gateway.http.endpoints.chatCompletions.enabled`). The flag is
  written explicitly on both config paths — the individual-variables build and
  the runtime patch applied to an existing/supplied config — so an explicit
  `false` overrides a stale `true` already present in a supplied config instead
  of leaving the endpoint enabled.

- New `dns_metrics_endpoint` role: exposes authoritative-DNS health as an authenticated
  JSON endpoint (`/.well-known/dns`, port 9107 by default) for Nyxmon `json-metrics`
  checks, following the `backup_metrics_endpoint` pattern — a root systemd timer
  (`dns-metrics-collector`) writes JSON to `/var/lib/dns-metrics/dns.json` and an
  unprivileged `dns-metrics-endpoint` service serves it with basic auth and staleness
  metadata. It probes nameservers **by address** (so it works before and independently
  of registrar glue) and exercises the full matrix of nameserver × address family ×
  transport × zone: one aggregate "DNS is up" boolean hides a half-dead nameserver, and
  a v6-only or TCP-only failure is invisible to a v4/UDP probe while still breaking real
  resolvers (TCP is mandatory for authoritative servers per RFC 7766). SOA queries use
  `+norecurse` and **require the `aa` flag** — a bare serial comparison can pass against
  a server that is not authoritative at all, because a misconfigured or recursive `named`
  can fetch the SOA from elsewhere and report a matching serial while serving nothing of
  its own. The role also compares SOA serials per zone across all nameservers and asserts
  that a recursion-desired query for a foreign name is `REFUSED`, catching an
  open-resolver regression. An unreachable endpoint is reported `unknown` rather than
  `failed` for the open-resolver probe, so one outage cannot also raise a bogus security
  alert.

  Collector-side IPv6 loss is handled honestly: the collector asks the kernel for a route
  and a global-unicast (`2000::/3`) source address via `connect()` on an unconnected UDP
  socket — no packets are sent, and Tailscale's ULA addresses are rejected because they
  prove nothing about internet reachability. When `meta.collector_ipv6_capable` is false
  the v6 results are `skipped` rather than `failed` and excluded from
  `summary.overall_ok`, while `summary.ipv6_tested` goes false so untested v6 cannot
  silently rot: "ns2 v6 is broken" and "I could not test v6" stay distinguishable.
  Optional per-nameserver `families`/`transports` overrides narrow the matrix for a known
  limitation of the collector's own vantage point; excluded cells stay visible as
  `skipped` with a `skip_reason`.

  All values a check rule needs sit at fixed, wildcard-free paths (`summary.*`, `meta.*`,
  `nameservers.<id>.*`) because Nyxmon's path resolver supports only `$.field.subfield`
  and list indices; `zones` is a list rather than a dict keyed by zone name, since zone
  names contain dots and the resolver splits on dots with no escaping. Every `*_ok`
  boolean means "nothing tested failed" and is paired with a `*_tested` flag, and
  `overall_ok` additionally requires that something was actually tested so an all-skipped
  run cannot look healthy. Probing uses `dig` from `bind9-dnsutils` (installed by the
  role) rather than a new Python dependency, so the check and its manual reproduction are
  identical; queries run concurrently and a single unreachable endpoint degrades only its
  own result. Defaults are RFC 5737/RFC 3849 documentation placeholders — real
  nameservers, addresses and zones come from the control repository.

  Documented in `roles/dns_metrics_endpoint/README.md` (why each check exists, the
  suggested Nyxmon rule paths, the exact `dig` commands to reproduce a red check by
  hand, and the HTTP status codes), rendered in the role catalog under deployment roles.

- `bind_authoritative_deploy` supports transfer-backed (secondary) zones. Zone types
  listed in the new `bind_zone_transfer_backed_types` variable (default
  `[slave, secondary]`, BIND's two names for the same thing) get a `primaries { ... };`
  block rendered from a required non-empty per-zone `primaries` value (a list, or a single
  address as a bare string; a mapping is rejected), resolve a relative
  `file` against `bind_working_dir` (`/var/cache/bind`, where named may write and the
  Debian AppArmor profile permits it), and are neither required nor copied from the
  controller. The exemption is an explicit allow-list rather than a `!= master` test, so
  `primary` and `hint` zones keep their controller-managed zone files; rendering the
  existing all-`master` zone lists is byte-identical to before.

- `bind_authoritative_deploy` renders TSIG keys. `bind_tsig_keys` (list of
  `{name, algorithm, secret}`, `algorithm` defaulting to `hmac-sha256`) is written as
  `key { ... };` stanzas to `bind_tsig_keys_file`
  (`/etc/bind/named.conf.keys`) at `bind_tsig_keys_mode` (`0640`, root:bind) — stricter
  than the `0644` used for the rest of the config, because a TSIG secret must not be
  world-readable. The rendering task is `no_log: true`, so the secret reaches neither
  Ansible output, nor the check-mode diff, nor the FastDeploy UI, and validation rejects
  an empty or `CHANGEME` secret. `named.conf` includes the file ahead of every other
  include so keys are defined before they are referenced; the include and the file are
  omitted entirely while `bind_tsig_keys` is empty, keeping `named.conf` byte-identical
  for existing callers. Key *names* are referenced from the already-verbatim
  `primaries` / `allow_transfer` / `extra_config` entries, so no new role code is
  needed for that side of it. Note when writing those entries that a BIND
  address-match list is a first-match-wins list of *alternatives*:
  `allow-transfer { 198.51.100.20; key "xfer"; };` permits a keyless transfer from
  that address **and** permits any key holder from anywhere. Requiring address *and*
  key needs the nested-negation idiom
  `allow-transfer { !{ !{ 198.51.100.20; }; any; }; key "xfer"; };`, written inline —
  a named `acl` cannot be supplied through `bind_extra_options`, whose lines render
  inside the `options { }` block where a top-level `acl` is illegal. The role README
  documents both, plus a worked primary/secondary example and the matching
  `also-notify { <addr> key "xfer"; };` without which `NOTIFY` is silently dropped
  and the secondary degrades to its SOA refresh timer. The keys file is checked with
  `named-checkconf` in its own right — rotating a secret leaves `named.conf`
  byte-identical, so that file's own validation never re-runs — which also means
  `secret` must be valid base64, as `tsig-keygen` emits. Emptying `bind_tsig_keys`
  deletes the keys file rather than leaving retired key material readable on disk.

- `bind_authoritative_deploy`'s post-deploy SOA check now uses `dig +norecurse` and
  requires the `aa` flag in addition to `status: NOERROR`, so a host running with
  recursion enabled cannot resolve the SOA from the public internet and mask a zone that
  failed to load. It retries `bind_verify_retries` times (default 12) with
  `bind_verify_delay` seconds (default 5) in between so a secondary's first zone transfer
  being in flight does not fail the run.

### Fixed

- `bind_authoritative_deploy` now flushes handlers before verification. Previously the
  `reload bind` handler ran at the end of the play, i.e. after `verify.yml`, so the SOA
  check inspected a named still serving its previous configuration. On an established
  server this was invisible; on a first install it failed hard, with named answering a
  root referral because none of the configured zones had been loaded yet.

### Added

- `mastodon_deploy` now installs `libvips-dev` and `libvips-tools`. Mastodon 4.6
  dropped ImageMagick support and requires libvips for media processing.
  `imagemagick` is retained so refs older than 4.6 stay deployable.

- `daybook_sessions_deploy` now manages a strict private-control supplied public
  repository policy and a content-free identity-migration operator rail. The
  rail prepares an owner-only crash-durable no-replace plan from exact draft GETs, preserves
  that plan across partial reruns, runs Daybook's separate dry-run/apply paths,
  and verifies the resulting attestation without exposing post content,
  credentials, or policy in argv/logs.

### Fixed

- `echoport_backup` restore runners for `homepage` and `python_podcast` (both the
  production-DB and staging variants) now stop the Django Tasks `db_worker` unit
  alongside the web service before dropping the database, and start it again
  afterwards. Previously only `SERVICE_NAME` was stopped, so the worker kept
  polling its task table every 5 seconds straight through `dropdb`/`createdb`,
  crashed with `relation "django_tasks_database_dbtaskresult" does not exist`,
  and needed a systemd restart to recover. The crash surfaced in Sentry as the
  misleading `InternalError: current transaction is aborted, commands ignored
  until end of transaction block`, because `django_tasks_db`'s `@retry()` re-runs
  `get_locked()` inside the same already-aborted transaction. Auxiliary units are
  configurable via `<prefix>_aux_service_names` and default to
  `<service>-db-worker`; units that do not exist on the restore host are skipped,
  so sites without a worker are unaffected. A trailing `.service` is stripped
  from the configured service name first, because the production-DB register
  playbooks pass `homepage.service` while the staging ones pass `homepage`.
  A failed probe raises instead of reporting the unit absent, so a transient SSH
  error cannot silently skip the guard.

- `wagtail_restore` gained the same protection: `wagtail_restore_extra_systemd_units`
  (default: the `wagtail_deploy` db_worker unit when `wagtail_db_worker_enabled`
  is true, otherwise empty) is stopped before the drop and started after
  migrations complete.

- `wagtail_deploy` now renders `DJANGO_SENTRY_ENVIRONMENT` / `SENTRY_ENVIRONMENT`
  from the new `wagtail_django_sentry_environment` variable (default
  `production`). Staging deployments share `config.settings.production`, and the
  Sentry SDK labels everything `production` when no environment is given, so
  staging incidents were indistinguishable from real production ones.

- `homeassistant_deploy` Custom Conversation provisioning: the config-flow
  helper no longer rewrites a loopback `homeassistant_api_url` to the default
  route IP before driving the flow. That rewrite discarded a configured scheme,
  port, or path and broke Home Assistant instances bound only to loopback or
  fronted by a localhost TLS/reverse proxy; the validated `homeassistant_api_url`
  is now used verbatim (matching the Wyoming integration). A helper failure now
  surfaces the sanitized diagnostic it wrote to its result file via a block
  `rescue`, instead of aborting on the `no_log` command task and leaving the
  operator with a censored failure. The reconfigure flow request drops the inert
  top-level `source` field and starts the flow the way Home Assistant's own
  Reconfigure button does (integration domain as handler plus the existing
  `entry_id`, which the config REST view promotes to a reconfigure context).

- `mastodon_deploy` no longer aborts when the Node version changes between
  deploys. `nvm version` exits 3 and prints `N/A` for a version that is not
  installed yet, which failed the resolve task before the install task's `N/A`
  gate could run, making the gate unreachable. Both resolve tasks now use
  `failed_when: false`, and the follow-up check reports rc/stdout/stderr instead
  of passing an empty result through to the runtime path facts.

### Security

- The Monday-after weeknote identity epoch now defaults absent and can render
  only when a clean pinned checkout verifies the exact private seed, mode-0600
  plan/attestation, and root-owned activation proof. Deploy and operator paths
  disable/unload before mutation and verify the exact installed rail; the
  scheduled launcher rechecks exact HEAD/root/cleanliness and uses an isolated
  frozen environment; both launchers verify the environment against a
  root-controlled checksum before sourcing it. Ordinary role deployment rejects activation; only a
  same-play fresh apply plus dedicated activation task can enable. All system
  deployments require managed launchd state and quiesce the exact unit before
  shared mutation; ordinary
  installs remain disabled/unloaded and cannot PATCH
  django-cast. Identity recovery requires django-cast commit `80b80928` and its
  content-free `previous_revision_id` contract.

### Added

- `logyard_deploy` can report systemd unit state for log producers through the
  health endpoint via the new `logyard_health_units` variable (default `[]`), so a
  dead producer is detected directly instead of being inferred from ingest going
  quiet. Each `{id, unit}` entry is published as `units.<id>` with `exists`,
  `load_state`, `active_state`, `sub_state` and `result`. `exists` is derived from
  `LoadState` rather than the exit code, because `systemctl show` exits 0 for units
  that do not exist. Unit state does not feed into the top-level `status` field.

### Fixed

- `logyard_vector_deploy` now renders a Loki sink that is valid under Vector 0.57's
  template confinement rules. Vector 0.57 rejects templated sink values without a
  literal static prefix, which made `vector.service` fail `ExecStartPre` with
  `exit 78/CONFIG` after an unattended upgrade from 0.56, silently stopping both
  journald log ingest and host-metric delivery from the same Vector instance. The
  constant `host`, `source_type`, and `environment` labels are now emitted as static
  literals, and the new `logyard_vector_allow_unconfined_label_templates` variable
  (default `true`) sets `dangerously_allow_unconfined_template_resolution` for the
  remaining per-event `service` and `level` labels. Label values are unchanged, so
  existing Loki selectors and dashboards keep working.
- `daybook_sessions_deploy` now accepts both the legacy boolean and current
  word-form `launchctl print-disabled` output when converging the dedicated
  weeknotes reconciler, preserving the disabled-by-default install gate on
  newer macOS releases.

### Security

- `weeknotes_home_deploy` now protects public-source HTTPS requests with shared
  Traefik Basic Auth while a higher-priority, validated RFC1918/Tailnet router
  preserves Studio's independent bearer-auth API calls. The role strips Basic
  credentials before proxying, redirects plain HTTP without reaching Django,
  and fails closed when the front-door credential is absent or malformed.
- `weeknotes_home_deploy` now requires and renders a dedicated bearer token for
  the private steering read/fold API, allowing Macmini and the Studio reconciler
  to share one managed secret instead of exposing those endpoints anonymously.

### Added

- `daybook_sessions_deploy` can install a dedicated Mac Studio draft-only
  weeknotes reconcile LaunchDaemon at 07:40 and 19:40 local time. The distinct
  unit, logs, mode-0600 environment, local state, and auth-only pi directory are
  managed independently from session shipping and quote classification; launchd
  activation defaults to disabled/unloaded and deployment never runs reconcile.
  OAuth is seeded once, preserves Pi refreshes on normal reapplication, and can
  be replaced only through explicit unloaded-unit rotation.

### Fixed

- `openclaw_deploy` now accepts bounded weeknotes write payloads up to 4,000
  characters by default, so normal long-form voice-note transcriptions are not
  rejected by the journal handler's previous 500-character ceiling.
- `openclaw_deploy` now installs version-pinned Codex plugins over host
  networking, avoiding npm resolution failures on hosts where Docker's
  transient default-bridge DNS cannot reach the configured resolver.
- `daybook_sessions_deploy` now configures Daybook's external quote lifecycle
  JSON state alongside the unused/used Markdown locations, exposes all three to
  classifier and handoff environments, and validates distinct safe locations on
  one compatible local or S3 backend without contacting storage; browser
  executable/profile validation remains local and strict.
- `openclaw_deploy` now writes managed `SOUL.md` and optional `USER.md` content
  into the active agent workspace instead of the OpenClaw state-directory
  root, can explicitly manage Telegram preview/tool-progress visibility, and
  manages DM session scope so shared bot deployments can isolate each sender's
  conversation history.
- `openclaw_deploy` now preserves the required `gateway.mode: "local"` setting
  in seeded and patched gateway configurations, preventing forced config
  renders from leaving current OpenClaw gateways in a restart loop.
- The Heis production Echoport runner now quotes compound remote SSH commands
  as a single argument, preventing operators such as `&&` from executing on
  the macmini backup runner instead of the production host.
- `paperless_deploy` now rejects missing or malformed release checksums and
  extracts new releases into a staging directory before switching the stable
  application symlink, preserving the working release if extraction fails.
- `marina_deploy` now excludes SQLite database and WAL/SHM runtime files from
  source rsync, preventing staging deploys from overwriting live Wagtail content
  with a controller-local `db.sqlite3`.
- `heis_deploy` now installs its host-side prerequisites and excludes SQLite
  database/WAL/SHM files from source rsync so code deploys preserve production
  content alongside the already-persistent media directory; page setup and
  content seeding can now be disabled independently for production, and
  optional canonical-host redirects support production alias domains.
  HTTP and TLS routers can now use separate host rules so an alias with pending
  DNS does not block ACME certificates for otherwise valid production names.

### Breaking Changes

- **Python 3.14+ required** - Dropped support for Python 3.8–3.13
  - Supports Python 3.14 (N-2 policy currently aligns with the latest stable release)
  - All roles and testing infrastructure now require Python 3.14+
  - Update your systems before upgrading to this version
- **ansible-core 2.20+ required** - Dropped support for Ansible 2.9-2.14
  - ansible-core 2.20 is the minimum version compatible with Python 3.14+
  - Update your Ansible installation before upgrading

### Added

- `openclaw_deploy` can now restore source-controlled workspace skills from
  controller-local files, including executable support scripts, while
  preserving interactive unmanaged skills and refreshing cached session skill
  snapshots whenever managed skill content changes.
- `daybook_sessions_deploy` now wires the browser-backed Archive quote
  classifier with validated Obsidian lifecycle files, a Helium executable,
  headless browser timing controls, a guarded dedicated profile, locked
  Playwright installation without bundled Chromium, redacted environment
  shipping, no-fetch pinned-checkout validation, real path/ownership checks,
  and a background/throttled launchd schedule. Headed mode is restricted to an
  Aqua user LaunchAgent.
- `heis_production_backup.py.j2`, a locked service-owned Echoport/FastDeploy
  runner for remote SQLite plus media backup and restore of a dedicated Heis
  production host. It uses exact immutable remote targets, bounded subprocesses,
  systemd restart watchdogs, short host-local backup snapshots, and automatic
  DB/media safety rollback for restores. Watchdogs remain armed until every
  service is proven active; restore runs migrations and requires an exact local
  HTTP 200 through Django's HTTPS proxy path before accepting the new data.
- `weeknotes_home_deploy` role to deploy daybook's `weeknotes.home` Django
  steering-comments service with PostgreSQL provisioning, uv-managed
  dependencies, systemd/gunicorn, Traefik routing, and a `/healthz` check.
- `weeknotes_home_deploy` can render a `WEEKNOTES_HOME_CAST_BASE_URL`
  environment setting so the service can link delivered drafts back to
  django-cast edit and preview pages.
- `daybook_sessions_deploy` role to validate a macOS `uv` runtime, install a
  pinned Daybook checkout, sync it with `uv`, install `trufflehog`, and run
  `daybook sessions ship` as a periodic launchd job using
  private-control-repo supplied MinIO credentials.
- `daybook_sessions_deploy` can skip git remote fetches for private,
  pre-staged Daybook checkouts while still checking out a pinned ref.
- `daybook_sessions_deploy` now supports user LaunchAgent installs for
  laptop-style macOS hosts that do not expose passwordless sudo or root SSH.
- `zfs_usb_replication` now persists drive-present success/failure separately
  from clean missing-drive skips, and `backup_metrics_endpoint` exposes stable
  policy-aware USB attempt, capacity, and protection-freshness health for alerting.
- `zfs_usb_replication` can now apply guarded pre-sync age retention to managed
  target-only snapshots while preserving every source-present common anchor and
  waiting for asynchronous ZFS frees before receiving new data.
- `delve_deploy` now installs an optional service-owned Discovery reviewed RSS
  collector oneshot/timer, passes bounded non-secret collector defaults including
  a 100-source run cap and 2-8 concurrency range, and documents the rollout
  boundary (no feed-pack seeding in the public role).
- `mail_relay_deploy` now supports
  `mail_relay_postgrey_whitelist_clients_extra` for managed postgrey whitelist
  entries in addition to the role defaults.
- `voxhelm_deploy` can now put transcription jobs into `remote_pull` mode with
  validated worker-token and shared S3 artifact settings, while
  `voxhelm_remote_worker_deploy` installs a pinned public-PyPI
  `voxhelm[diarization]` worker on macOS and runs it under launchd.
- `voxhelm_ingress_deploy` now blocks `/v1/internal` by default at the Traefik
  edge, with an explicit separate allowlist for deliberately private worker
  routes.
- `tailscale_metrics_endpoint` role to expose authenticated Tailscale login
  state and node-key expiry JSON for Nyxmon monitoring.
- `voxhelm_deploy` now supports production pyannote speaker diarization wiring,
  including optional `uv sync --extra diarization` installation, protected
  Hugging Face token env rendering, and validation when the backend is enabled.
- `nyxmon_storage_exporter` now caches successful ZFS pool samples and reuses them during quiet-hours pool skips, keeping capacity JSON paths stable for monitoring while marking cached values explicitly.
- `os_apt_maintenance` endpoint responses now expose `$.meta.state_reboot_required` so operators can inspect the reboot-required value from the durable state file separately from the live marker.
- `os_apt_maintenance` role for host-local apt update/dist-upgrade/autoremove/autoclean timers with durable JSON state and an optional authenticated Nyxmon endpoint.
- `wagtail_deploy` now supports a stable `wagtail_db_worker_id` and passes it to Django Tasks `db_worker --worker-id`, allowing each deployed site to run a distinct database-backed task worker
- `wagtail_deploy` now includes a `redirect-www` Traefik middleware that strips the `www.` prefix via regex redirect (302), applied unconditionally to the HTTPS router
- `headless_mode` role to persist hosts on a non-graphical systemd target and disable running display-manager services without requiring a reboot
- `paperless_deploy` can now promote existing Paperless users to active staff superusers during deploy via `paperless_existing_superusers`
- Takahe lifecycle roles: `takahe_shared`, `takahe_deploy`, `takahe_backup`, `takahe_restore`, and `takahe_remove` with systemd services, nginx caching/accel proxy, Traefik routing, and PostgreSQL provisioning
- Mastodon lifecycle roles: `mastodon_shared`, `mastodon_deploy`, `mastodon_backup`, `mastodon_restore`, `mastodon_maintenance`, and `mastodon_remove` with rbenv+nvm runtimes, systemd services, Traefik routing, and backup/restore tooling
- `open_webui_deploy` and `open_webui_remove` roles to run Open WebUI via Docker Compose with Traefik routing, persistent storage, and optional basic auth
- `open_webui_venv_deploy` and `open_webui_venv_remove` roles for a uv-managed venv deployment with systemd, Traefik routing, and persistent data
- `zfs_syncoid_replication` role for scheduled syncoid replication with alert hooks and optional spindown script
- `zfs_usb_replication` role for USB-attached ZFS replication with device detection and optional alerts
- `minio_offsite_replication` role to pull MinIO archives from a remote host into offsite storage via systemd timer, rsync/SSH, and alert hooks
- `mail_offsite_replication` role to pull maildir + staged DB/config artifacts from a remote host into offsite ZFS storage with post-sync snapshots, status markers, and alert hooks
- `encrypted_volume_prepare` role to verify, unlock, and mount LUKS data volumes with keyfile support, UUID validation, crypttab/fstab wiring, and a validate-only dry run
- `nyxmon_backup` role for SQLite-safe snapshots with metadata, manifests, and automatic archive fetches
- `nyxmon_restore` role with staging validation, safety snapshots, rollback support, and service verification
- `ollama_install` role to install and run Ollama on macOS via Homebrew with launchd management
- `ollama_remove` role to unload launchd, remove the plist, and optionally remove data/logs, service user, and Homebrew package
- `docker_install` role to install Docker Engine + Docker Compose v2 (plugin) on Ubuntu via the official Docker apt repository
- `shell_basics_deploy` role to install fish, modern CLI tools (btop, bmon, sysstat/iotop, tealdeer, eza), set shell/editor defaults, and keep chezmoi current via upstream installer
- `snappymail_deploy` role to install SnappyMail from upstream archives (PHP-FPM + nginx), wire IMAP/SMTP defaults, persist data under `/mnt/cryptdata/snappymail`, and expose via Traefik
- ReadTheDocs integration with Sphinx and MyST parser
  - Browsable documentation at <https://ops-library.readthedocs.io/>
  - Furo theme for modern, clean appearance
  - Automated role documentation from individual READMEs
  - Just commands for documentation workflow (docs-build, docs-watch, etc.)
  - Documentation validation script (validate_docs.py)
- Migrated to uv for Python dependency management
  - Faster dependency resolution and installation
  - Simplified justfile commands using `uv run`
  - Removed manual venv activation requirements
- `homeassistant_deploy`, `homeassistant_backup`, and `homeassistant_remove` roles to cover the full lifecycle alongside the existing restore workflow
- `homeassistant_restore` role to validate archives, create safety snapshots, restore files, and roll back on failure
- FastDeploy backup & restore workflow:
  - `fastdeploy_backup` role with metadata-rich snapshots, disk-space validation, and archive support
  - `fastdeploy_restore` role with safety snapshots, permission fixes, health-check retries, and rollback automation
- Paperless-ngx suite: `paperless_deploy`, `paperless_backup`, `paperless_restore`, `paperless_postgres`, and `paperless_remove` roles for deployment, disaster recovery, and safe removal
- `redis_install` role to provision standalone Redis instances with optional authentication, persistence, and memory tuning
- `postgres_install` role to install PostgreSQL with manageable config, databases, users, and extensions
- `minio_deploy` role to provision MinIO with dual-router Traefik exposure, security hardening, and optional client bootstrapping
- `minio_remove` role to destructively remove MinIO with confirmation, optional data preservation, and Traefik cleanup
- Dynamic DNS support in `dns_deploy`, adding an opt-in LiveDNS updater with dedicated service accounts, timers, and IPv4/IPv6 support
- UniFi lifecycle roles: `unifi_deploy`, `unifi_backup`, `unifi_restore`, and `unifi_remove` (Mongo-auth aware, Traefik/HA integration, Justfile wiring, docs)
- Navidrome lifecycle roles: `navidrome_deploy`, `navidrome_backup`, `navidrome_restore`, and `navidrome_remove` (systemd binary install, Traefik basic auth, rescan timer, backup/restore tooling)

### Changed

- `openclaw_deploy` now installs the official Codex app-server plugin at the
  OpenClaw-matching release and supports an
  explicit canonical `auth.order.openai` profile list so deployments can require
  ChatGPT/Codex subscription OAuth for OpenAI agent turns without silently
  falling back to API-key billing. Documentation examples now use upstream
  stable `v2026.6.11`.
- `mail_relay_deploy` now documents IPv4-only relay mode and exposes
  `mail_relay_smtp_address_preference` so deployments can avoid or de-prioritize
  IPv6 while PTR/forward DNS is not aligned for outbound delivery.
- `voxhelm_remote_worker_deploy` now defaults to `caffeinate -ims` so macOS
  remote workers stay awake during long jobs while allowing display sleep.
- `tailscale_metrics_endpoint` now defaults node-key expiry alerts to warning
  inside 3 days and critical inside 1 day.
- `zed` role scrub timers can optionally wait for completion and run a post-scrub spindown hook
- Unit tests for OpenClaw metrics collector canary behavior and schema invariants (`tests/unit/test_openclaw_metrics_collector.py`)

### Fixed

- `daybook_sessions_deploy` now uses an explicit boolean assertion for the S3
  session path check, keeping the role compatible with stricter Ansible
  conditional validation during real macOS deploys.
- `daybook_sessions_deploy` now runs the Daybook checkout update under a login
  shell for the service user, avoiding macOS sudo current-directory failures.
- `openclaw_deploy` synthetic canaries now use fresh per-attempt session ids
  derived from the configured canary prefix and clean up generated canary
  session files after a bounded retention window, preventing reused canary
  history from causing context overflow, malformed markers, and retry lock
  contention.
- `openclaw_deploy` metrics collector now treats parseable nonzero
  `health --json` output as collected health data, so transient Telegram probe
  failures do not set `collector_ok=false`.
- `nyxmon_storage_exporter` now parses in-progress and paused ZFS scrub
  timestamps without confusing the weekday `Mon` for a completed-scrub `on`
  marker, avoiding false scrub-age warnings while a pool is actively scrubbing.
- Deploy roles now build stat assertion labels and error messages from the
  original loop item instead of registered result invocation metadata,
  restoring compatibility with newer ansible-core controllers.
- Collection metadata now declares the documented ansible-core 2.20+ runtime
  requirement.
- `wagtail_deploy` rsync deployments now exclude the managed `.env` file and collected `/staticfiles` directory, preventing failed deploys from clobbering runtime secrets or deleting WhiteNoise assets before `collectstatic` runs.

### Changed

- `homeassistant_deploy` now performs its read-only Python, Home Assistant, and
  Matter Server inspection commands during Ansible check mode, preventing
  upgrade preflights from failing on missing skipped-command output, and its
  temporary API helper cleanup no longer produces false idempotency changes.
  Virtualenv inspection and API helper commands now run as the Home Assistant
  service user, with ownership reconciliation to prevent root-owned bytecode
  caches from blocking runtime integration installs.
- `homeassistant_deploy` no longer renders the removed `system_monitor` and
  `discovery` YAML integrations and migrates the role-generated legacy blocks
  out of existing managed configurations.
- `os_apt_maintenance` endpoint responses now derive `$.reboot_required` from the live `/var/run/reboot-required` marker so monitoring clears immediately after a successful reboot.
- `mastodon_backup` now excludes Mastodon's refetchable `public/system/cache` subtree from local media backups by default and records the media exclude list in backup manifests.
- `mastodon_backup` now runs `pg_dump` as the backup owner by default so password-authenticated dumps can write into root-owned backup directories.
- `openclaw_deploy` now uses a shallow single-tag/branch source checkout so upstream branch namespace conflicts do not block tag-pinned deployments.
- `openclaw_deploy` now renders the managed slash-skill session manifest without invalid inline Jinja comments.
- `openclaw_deploy` now normalizes legacy Telegram streaming aliases in persisted gateway configs before restarting newer OpenClaw releases.
- `openclaw_deploy` metrics collector now recognizes the current OpenClaw Telegram health shape (`running`/`connected`) when deriving `telegram_probe_ok`.
- `openclaw_deploy` documentation now uses upstream stable `v2026.6.10` in examples and validation hints.
- `paperless_deploy` now defaults to Paperless-ngx 2.20.15 and supports checksum verification for known upstream release archives.
- `paperless_deploy` now restarts Paperless services before health checks when a release symlink or package install changes, preventing upgraded deployments from leaving old worker processes serving the previous release.
- `homeassistant_deploy` now supports Home Assistant 2026.5 on Python 3.14, installs host-specific integration requirements before startup, removes legacy MET weather YAML when requested, and isolates the Matter Server in its own virtualenv to avoid Matter package namespace collisions.
- `unifi_deploy` now reconciles the Home Assistant UniFi admin when it already exists, including password hash drift and missing readonly site privileges.
- `dns_deploy` now supports Unbound cache prefetch, stale-TTL reset, optional RFC 8767 timeout tuning, recursion queue sizing, and disables Ubuntu's legacy resolvconf helper when the role manages `/etc/resolv.conf`
- `dns_deploy` blocklist refreshes now tolerate individual download failures, understand both hosts-style and AdGuard-style lists, and document the limits of `serve-expired` during WAN reconnects
- `netplan_config` now rejects interfaces that combine `dhcp4: true` with a manual IPv4 default route, documents DHCP-backed hosts to use DHCP-managed default routes, and offers an optional post-apply `networkctl reconfigure` recovery pass for `networkd` hosts stuck in a failed link state
- Closed out the refactor documentation pass so top-level docs and role READMEs
  describe the landed deploy/restore helper boundaries as complete work and
  frame remaining items as normal follow-up maintenance instead of pending
  refactor waves
- `dns_deploy` now exposes optional Unbound `serve-expired` controls and documents `forward_first` guidance for the root zone so resolver failover behavior is explicit
- `nyxmon_restore` now mirrors the Home Assistant structure (validate/prepare/restore/verify/cleanup), keeps cleanup in a top-level block/always flow, adds restore-phase block/rescue rollback, conditional restores, handler flush, and health checks
- `nyxmon_deploy` systemd service now launches Granian instead of Gunicorn to match the upstream project
- `ollama_install` stops any Homebrew-managed Ollama service by default, stops conflicting user-level `ollama serve` processes, and ensures the launchd service is running
- Updated README.md with prominent link to ReadTheDocs
- Updated repository URLs to <https://github.com/ephes/ops-library>
- Modernized Python tooling: uv replaces traditional pip/venv workflow
- Removed `docs-setup` command (auto-handled by uv)
- `fastdeploy_deploy` now depends on `postgres_install` for database provisioning (removing the legacy inline PostgreSQL tasks)
- `uv_install` detects alternate uv installations, relinks to newer binaries automatically, and enables `uv_update_existing` by default to keep hosts current
- `fastdeploy_deploy` implements Traefik's dual-router pattern with IP-based allow lists, bcrypt-hashed basic auth, security headers, and compression middleware
- Paperless roles now support Python 3.14 and include an optional ocrmypdf patch to keep OCR workflows unblocked
- `paperless_deploy` no longer installs `default-libmysqlclient-dev`, avoiding apt conflicts with MariaDB development packages on Ubuntu 24.04 when using the PostgreSQL backend
- `redis_install` enables config validation by default to catch syntax and runtime issues before service restarts
- `nyxmon_deploy` and `homelab_deploy` switch from Granian to Gunicorn and gained configurable Python version management (defaulting to 3.13)
- `nyxmon_deploy` now enforces the same dual-router authentication policy as other public services, including validation and hashed credentials
- `nyxmon_deploy` now flushes handlers and smoke-validates the live monitoring worker's OpsGate submit and approval URLs so stale approval-link wiring fails during deploy
- DNS deployment/removal flows hardened with improved resolver management, legacy `unbound_only` port detection, and safer variable validation
- `snappymail_deploy` now writes managed domain configs as `.json`, removes conflicting legacy `.ini` files, and supports `snappymail_remove_domains` cleanup for stale domain overrides
- `open_webui_deploy` documentation now calls out the `studio.tailde2ec.ts.net` hostname, Traefik config path/basic auth wiring, and ops-control preflight bypass flag
- `open_webui_remove` now defaults to non-destructive options and supports removing compose/env files separately from the site directory
- `zfs_usb_replication` gained optional syncoid identifiers, force-export, and spindown hooks to prevent snapshot collisions and park disks after USB runs
- `openclaw_deploy` synthetic canary collection now sets explicit collector `TimeoutStartSec=600`, keeps dedicated canary session-id routing, and preserves stable canary metadata keys (`agent`, `timeout_seconds`, `session_id`) in payload defaults

### Fixed

- `backup_metrics_endpoint` and `openclaw_deploy` collector timers now schedule from timer activation and collector completion, preventing post-reboot or post-restart `active (elapsed)` timers with no next run.
- `mail_spam_deploy` now configures the Rspamd APT repository with a scoped `signed-by` keyring and removes the legacy global apt-key entry, avoiding apt-key deprecation warnings on Ubuntu 24.04.
- `mastodon_backup` now restarts Mastodon services after failed backup payload capture, preventing `pg_dump` or media-copy failures from leaving services stopped.
- `mastodon_restore` now makes the staged database dump path traversable by the restore OS user before running `pg_restore`, while keeping the default peer-auth restore user.
- `wagtail_deploy` now protects the top-level `/cache` directory from rsync deletion and recreates `wagtail_cache_dir` after source deployment, preventing Django file-based cache failures like the python-podcast feed incident
- `mastodon_deploy` now resolves the concrete Node version path from `nvm version` instead of guessing an `nvm` directory name from `.nvmrc`, fixing deploys where values like `24.10` install under `v24.10.0` and otherwise break `yarn` during asset precompile
- `mastodon_deploy` now clears Rails cache after source, runtime, dependency, migration, or asset-build changes so stale cached instance metadata does not survive Mastodon upgrades in Redis after the services restart
- `mastodon_deploy` now restarts the web, Sidekiq, and streaming services when source, runtime, dependency, migration, or asset-build tasks change, so upgrades and recovery reruns do not leave long-running processes serving the previous release until a manual restart
- `logyard_vector_deploy` now disables the Vector Loki sink startup health check by default and validates staged config with `--skip-healthchecks`, preventing transient Logyard/Loki 5xx responses from blocking Vector service startup after package upgrades or restarts.
- `dns_deploy` now points its default AdGuard DNS filter source at the maintained upstream URL, avoiding daily blocklist refresh failures from the retired GitHub raw path
- `sanoid` now renders dataset `use_template` values using the bare template name expected by Sanoid instead of the literal section header, restoring per-dataset retention and pruning behavior for roles like Fractal Time Machine backups
- Home Assistant presence automations now include the default file to prevent missing automation imports after deployment
- `dns_remove` cleans up DDNS units reliably and no longer crashes on undefined variables during selective removal
- `unifi_restore` now re-imports MongoDB dumps, honors host/port overrides, and ships with sane defaults so UniFi logins and controller state survive a remove/deploy/restore cycle
- `unifi_deploy` gracefully skips the Home Assistant integration on the very first bootstrap when the UniFi “default” site does not exist yet, avoiding infinite waits on greenfield installs
- `open_webui_deploy` now validates the bind host and host port range to catch invalid settings earlier
- `zfs_usb_replication` now creates `/etc/exports.d` before mount and auto-sets `canmount=off` on existing recursive+readonly targets to avoid mountpoint creation failures on subsequent runs

## [2.0.0] - 2025-10-09

### Breaking Changes

- **REMOVED**: `python_app_systemd` role - Legacy manifest-driven deployment (use dedicated `*_deploy` roles instead)
- **REMOVED**: `python_app_django` role - Legacy manifest-driven Django deployment (use dedicated `*_deploy` roles instead)

### Added

- `homelab_deploy` role - Django/Granian deployment with dual router Traefik authentication
- `homelab_remove` role - Safe removal with data preservation options
- `traefik_deploy` role - Install and harden Traefik with Let's Encrypt automation, architecture auto-detection, and smoke tests
- `traefik_remove` role - Safe Traefik uninstallation with confirmation gates and preservation toggles
- `dns_deploy` and `dns_remove` roles - Manage Pi-hole/Unbound (later Unbound-only) DNS stacks with split-DNS views and clean removal
- Dual router authentication pattern for Traefik (internal: no auth, external: basic auth)
- Comprehensive Traefik security documentation
- Broken venv detection and auto-removal in Python deployment tasks
- Build ignore patterns in galaxy.yml for faster collection builds
- Comprehensive documentation structure with README.md and ARCHITECTURE.md
- CLAUDE.md for AI assistant context
- Standardized role README template

### Changed

- Streamlined role documentation for consistency
- Fixed systemd service template to remove `ProtectHome` for services in /home
- Improved validation.yml to handle undefined variables gracefully in homelab_remove
- Removed legacy role documentation pages
- Updated role index to reflect removal
- Added migration guidance for users of removed roles
- Updated uv_install examples to use modern deployment pattern
- `nyxmon_deploy` gained rsync support for additional source directories and smarter uv-based dependency management (pyproject validation, lock cleanup, mode-aware sync commands)

### Fixed

- Template evaluation crashes in homelab_remove when home directory doesn't exist
- Undefined variable errors in removal validation when database/media checks are skipped
- Permission issues with Python virtual environments on redeployment

### Migration Guide

If you were using `python_app_systemd` or `python_app_django`:

1. Migrate to dedicated roles: `fastdeploy_deploy`, `nyxmon_deploy`, `homelab_deploy`, etc.
2. Follow the role development guide to create custom deployment roles if needed
3. The old `services.d/` manifest workflow is no longer supported

## [1.0.0] - 2024-09-22

### Added

- Initial release of ops-library collection
- Core service deployment roles:
  - `fastdeploy_deploy` - Deploy FastDeploy platform
  - `nyxmon_deploy` - Deploy Nyxmon monitoring service
  - `fastdeploy_remove` - Remove FastDeploy service
  - `nyxmon_remove` - Remove Nyxmon service
- Service registration roles:
  - `apt_upgrade_register` - Register apt upgrade tasks with FastDeploy
  - `fastdeploy_register_service` - Generic service registration helper
  - `fastdeploy_self_deploy` - FastDeploy self-deployment registration
- Bootstrap roles:
  - `ansible_install` - Install Ansible and dependencies
  - `uv_install` - Install uv for Python environment management
  - `sops_dependencies` - Install SOPS/age prerequisites
- Testing infrastructure:
  - `test_dummy` - Example service for testing deployment patterns
- Legacy compatibility roles:
  - `python_app_django` - Django application deployment (deprecated)
  - `python_app_systemd` - Systemd service management (deprecated)

### Security

- Strict validation of secrets to prevent "CHANGEME" placeholder values
- SOPS/age encryption support for secrets management
- Sudoers configuration for privilege separation

<!-- markdownlint-enable MD024 -->

## Role Version History

### fastdeploy_deploy

- **1.0.0** (2024-09-22): Initial release with rsync/git deployment support

### nyxmon_deploy

- **1.0.0** (2024-09-22): Initial release with Telegram integration

### apt_upgrade_register

- **1.0.0** (2024-09-22): Initial release with SSH key management

[Unreleased]: https://github.com/ephes/ops-library/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/ephes/ops-library/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/ephes/ops-library/releases/tag/v1.0.0
