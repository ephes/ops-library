# Testing Guide for ops-library

`ops-library` uses a few different validation layers. The contributor workflow keeps the
practical path and the strict path explicit. Repo-wide `ansible-lint` is clean only against the
reviewed baseline in `.ansible-lint-ignore` (see [Strict lint baseline](#strict-lint-baseline)).

## Prerequisites

- Python 3.14+ on the controller
- `uv`
- Docker, Colima, or another compatible container runtime for Molecule scenarios

## Recommended Workflow

```bash
# One-time bootstrap
just setup

# Default contributor validation path
just test

# Stricter gate for slices that need failing lint
just validate-strict

# Focused role syntax/smoke checks while iterating
just test-role fastdeploy_register_service

# Focused Molecule coverage for high-risk roles
just molecule-test fastdeploy_register_service
just molecule-test fastdeploy_restore
just molecule-test unifi_restore
```

`just test` currently runs:

- `just test-roles`
- `just lint`
- `just docs-build` (strict Sphinx build with `-E -n`)
- `just docs-lint`

`just validate-strict` swaps in `just lint-strict` for the same sequence.
Use `just lint` only as a quick summary helper. It intentionally does not fail the run.

## Credentials and no_log

`just test` and `just lint-strict` run `just test-secret-no-log`, a static check
(`scripts/check_secret_no_log.py`) over every YAML file under `roles/` except Molecule scenarios.
It fails when a task sends a credential without `no_log: true`:

- a `uri` task with an `Authorization`, token, API-key, secret, password or cookie header, a header
  value or URL that renders a secret-named variable, `url_password`, or a `body`/`src` that renders a
  secret-named variable (`*password*`, `*secret*`, `*token*`, `*api_key*`, `*private_key*`,
  `*access_key*`; names ending in `_file`, `_path`, `_hash`, `_dir` or `_name` do not count);
- a `command`/`shell`/`raw` task whose command line has an `Authorization:` header or a `Bearer` token.

The check also reads `action:`/`local_action:` forms (including `k=v` arguments and a nested `args`) and
task-level `args:`; a `uri` task whose arguments come from a bare `{{ template }}` counts as
credential-carrying, and free-form `k=v` arguments count when they mention any credential-like word. It accepts Ansible tags such as
`!vault`, and fails on any file it cannot parse rather than skipping it.
`no_log: true` may come from the task or an enclosing block or play. A templated `no_log` does not
count. `ansible-playbook -vvv` prints every module argument, headers included, so `failed_when:
false` alone does not keep a token private. To keep failures debuggable, add a separate task that
prints only `status` and `json` (the server's response body) of the registered result. Do not print
`msg`: for a malformed header value it quotes the header, token included.

## Strict lint baseline

`just lint-strict` runs `ansible-lint roles/` and exits non-zero on any finding that is not
covered by `.ansible-lint-ignore`. The baseline lists existing debt as `<file> <rule> skip`
entries, grouped by rule with a note on why each group was not fixed mechanically:

- `name[prefix]`: task names in included task files without the `<file stem> | ` prefix.
- `command-instead-of-module`, `command-instead-of-shell`, `partial-become[task]`: fixing these
  changes behaviour (idempotence, change reporting, privilege escalation) and needs a reviewed
  change per task.
- `jinja[spacing]`: multi-line expressions and Jinja blocks inside shell scripts.
- every finding in `roles/homelab_*`, pending the homelab lifecycle rework.

An entry suppresses its rule for the whole file, so a new violation fails the gate unless the same
rule is already listed for that file. Rules:

- Do not add entries for new code. Fix the finding instead.
- When you clear a file's findings for a rule, delete that entry.
- `just lint-strict` is not part of `just test`. Run it (or `just validate-strict`) before
  committing changes to roles; the pre-commit `ansible-lint` hook reads the same baseline.

Some baselined findings still print as `(warning) # ignored`: ansible-lint 25.11 honours `skip`
reliably only when a file has a single baselined rule. They do not fail the run. To see all
suppressed findings, move the file aside and run the linter:

```bash
mv .ansible-lint-ignore /tmp/ansible-lint-ignore && \
  uv run ansible-lint roles/ </dev/null; mv /tmp/ansible-lint-ignore .ansible-lint-ignore
```

Run `ansible-lint` with `</dev/null` from non-interactive shells (agents, CI wrappers): it aborts at
startup when stdin is a non-blocking handle.

## Secret file modes

`just test-secret-file-modes` (part of `just test`) scans every `template`/`copy` task. When the
template source or inline `content` uses a secret-named variable (`*password*`, `*secret*`,
`*token*`, `*api_key*`, `*private_key*`, `*access_key*`; names ending in `_path`, `_file`,
`_hash` and similar do not count), the task must set an explicit octal `mode` with no "other"
bits, such as `0600` or `0640` with the service group. A `{{ var }}` mode is resolved from the
role defaults. systemd unit templates (`*.service.j2`, `systemd_service*.j2`) must not reference secrets at all: unit
files are world-readable and `systemctl show` prints `Environment=`. Use an `EnvironmentFile=`
or a credentials file instead.

## Backup service restart

`just test-backup-service-restart` (part of `just test`) loads every
`roles/*_backup/tasks/*.yml` file. Each `systemd`/`service` task with
`state: stopped` must sit inside a `block` whose `always` section starts the
same unit (the same `name`, or a loop over the stop task's registered results).
Otherwise a failed copy or dump step would leave the service down. Static
`import_tasks`/`include_tasks` files are checked where they are imported, and a
`when: var == 'value'` item that contradicts the import's `vars` drops the task
at that site (this is how `unifi_backup/tasks/services.yml` is checked).

## SSH forwarding identity fixtures

`just test-ssh-forwarding-roles` runs the descriptor, ownership, recovery and race
regressions locally. Identity fixtures explicitly set their temporary root's group
to the test process's primary group before creating children. macOS inherits the
parent directory's group, which may otherwise be `wheel` under the system temp
root even when the configured test identity belongs to `staff`.

This setup changes only fresh test directories. The production helper still
rejects mismatched configured ownership. A dedicated negative test verifies
that a non-root operation rejects a mismatched configured group without changing
the directory.
Do not skip ownership or race assertions to make the suite pass on macOS.

## Molecule Scenarios

Molecule coverage lives under `roles/<role>/molecule/default/`.

Common commands:

```bash
just molecule-test <role>
just molecule-converge <role>
just molecule-verify <role>
just molecule-destroy <role>
just molecule-login <role>
```

### Run-scoped container names

Docker container names are global to the daemon, so two checkouts running the
same scenario must not use the same platform name. Every `molecule.yml` names
its platforms with the `${MOLECULE_RUN_ID:-local}` token, and keys
`host_vars` by the same names:

```yaml
platforms:
  - name: "instance-${MOLECULE_RUN_ID:-local}"
    image: geerlingguy/docker-ubuntu2404-ansible
provisioner:
  inventory:
    host_vars:
      "instance-${MOLECULE_RUN_ID:-local}":
        ansible_user: root
```

New scenarios must follow the same pattern: append `-${MOLECULE_RUN_ID:-local}`
to every platform `name`, to every `host_vars` key, and to the `name` of any
Docker network listed under a platform's `networks`. Target hosts in
playbooks with `hosts: all` (or a group), never with a literal platform name.
`just test-molecule-run-isolation` (part of `just test`) fails on a fixed name
such as `name: instance`.

All `just molecule-*` recipes run Molecule through `scripts/molecule-run.sh`,
which exports `MOLECULE_RUN_ID`, a matching `MOLECULE_EPHEMERAL_DIRECTORY` and
a run-scoped `ANSIBLE_HOME`, all under
`~/.cache/ops-library-molecule/<run-id>/<role>/<scenario>/`. Molecule's
prerun installs the checkout as the `local.ops_library` collection into
`$ANSIBLE_HOME/collections`; with a shared `~/.ansible` parallel checkouts
raced on that install and ran each other's role code. The wrapper puts the
run's collections first on `ANSIBLE_COLLECTIONS_PATH`, followed by the shared
`~/.ansible/collections` (for `community.docker` and friends). A scenario that
sets `ANSIBLE_COLLECTIONS_PATH` in its provisioner env must start it with
`${ANSIBLE_COLLECTIONS_PATH:-~/.ansible/collections:/usr/share/ansible/collections}`.

- `just molecule-test*` uses a fresh random ID per invocation. The scenario's
  destroy step removes its containers. After a failure, or on INT/TERM, the
  wrapper first stops the whole Molecule process group (TERM, then KILL after
  `OPS_LIBRARY_MOLECULE_STOP_TIMEOUT` seconds, default 30) and then runs
  `molecule destroy` for the same ID, which only touches that run's
  containers.
- `molecule-converge`, `-verify`, `-login` and `-destroy` use an ID that is
  stable per checkout, role and scenario, so a debugging session across
  separate invocations addresses the same containers.
- An exported `MOLECULE_RUN_ID` (lowercase letters, digits, `-`; at most 24
  characters) overrides both; give each scenario that runs at the same time
  its own value. Running `molecule` directly without the wrapper falls back to
  the shared `local` suffix and is not isolated.

Playbook-based tests under `tests/*.yml` follow the same rule for scratch
files: build `/tmp` paths from the play variable
`ops_test_tmp_prefix: "ops-library-{{ (playbook_dir | hash('sha1'))[:10] }}-"`
(for example `"/tmp/{{ ops_test_tmp_prefix }}test-my-role.env"`) instead of a
fixed `/tmp/test-...` name.

Current role-local scenarios include infrastructure and restore boundaries such as:

- `apt_upgrade_register`
- `fastdeploy_register_service`
- `fastdeploy_restore`
- `nyxmon_deploy`
- `shell_basics_deploy`
- `test_dummy`
- `unifi_restore`

When adding coverage, prefer small role-local fixtures that prove the risky behavior directly:

- privilege boundaries (`sudo`, service users, restricted runners)
- restore rollback or rescue paths
- idempotent file rendering and ownership
- validation-only dry runs

## Legacy Shell Helpers

Legacy shell helpers still exist for repo-local syntax and ad-hoc checks:

```bash
./test_runner.sh all
./test_service.sh <role> localhost syntax
```

They are convenience tools, not the preferred contributor gate.

## Documentation Validation

Run these directly when working on docs-heavy changes:

```bash
just docs-build
uv run --extra docs sphinx-build -E -n -b html docs/source docs/build/html-clean
just docs-lint
```

`just docs-build` is strict and should stay warning-free.

## Pre-commit

```bash
just pre-commit
just pre-commit-update
```

The Ansible hook uses the same `uv run ansible-lint` toolchain as contributor
checks. The Jinja hook parses templates with Jinja2 without rendering variables,
executing filters, or accessing inventory. Both use the project toolchain. Secret scanning covers supplied files of every
extension without a generated baseline; formatting hooks retain their previous source-file scope. Large-file and
private-key checks intentionally cover all extensions. Only the exact `CHANGE_ME` sentinel is
excluded, so replacing it with a credential is still detected. Long role-table rows are allowed;
the changelog permits repeated historical category headings. MyST include wrappers
locally suppress the first-heading rule because their included README supplies it.

Docker integration tests require a running runtime. On macOS, start the configured
Colima VM with `colima start` before `just test`; `just` detects its socket.

### Traefik transactions

`just test-traefik-transactions` runs the failure and journal regression tests.
On an ARM64 Docker host, `just test-traefik-transactions-integration /path/to/cache`
runs a disposable systemd container with networking disabled. The cache must contain
`3.5.3/traefik_v3.5.3_linux_arm64.tar.gz` and
`3.7.12/traefik_v3.7.12_linux_arm64.tar.gz`; the fixture verifies exact published
checksums before execution. It exercises a real failed-acceptance rollback,
reviewed resume, binary update, alias-only update, no-op PID preservation and ACME
preservation. The runner removes only its own container ID. This is a mechanics
fixture, not native-x86 validation or production ingress/mitigation evidence.

The Traefik Linux transaction integration also exercises pre-enrollment ownership
repair and inactive linked-service retirement against real systemd. It checks
preserved proxy PID/data/middleware and refuses active services, route drift,
invalid candidates, changed middleware, unresolved journals and enrollment.

## Redis optional validator regression

The opt-in [Redis validation fixture](tests/redis_validation/README.md) diagnoses
the old no-listener failure and tests actual valid/invalid configuration handling
with Redis, Ansible and systemd in a disposable local Docker Linux VM. Run
`python3 tests/redis_validation/run.py` from the repository root; see its README
for privilege/isolation boundaries and runner safety checks. It is separate from
the default contributor suite and needs macOS Docker plus image-build network
access.
