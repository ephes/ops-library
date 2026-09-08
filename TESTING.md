# Testing Guide for ops-library

`ops-library` uses a few different validation layers. The contributor workflow should make the
practical path and the strict path explicit instead of pretending repo-wide `ansible-lint` is clean
when it is not.

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
