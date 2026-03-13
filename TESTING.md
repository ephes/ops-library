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
