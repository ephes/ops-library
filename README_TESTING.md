# Testing ops-library

## Quick Start

```bash
# Bootstrap the local environment
just setup

# Run the default contributor validation path
just test

# Run the stricter gate when you want lint failures to stop the run
just validate-strict

# Run focused checks while iterating
just test-role fastdeploy_register_service
just molecule-test fastdeploy_register_service
```

## What `just test` Covers

- role test harness (`just test-roles`)
- no_log check for credential-carrying tasks (`just test-secret-no-log`)
- non-failing lint summary (`just lint`)
- strict Sphinx build (`just docs-build`)
- docs consistency checks (`just docs-lint`)

`just validate-strict` uses `just lint-strict` in the same sequence. `just lint-strict` fails on any
`ansible-lint` finding not listed in the reviewed baseline `.ansible-lint-ignore`; see
"Strict lint baseline" in `TESTING.md`. It also runs `just test-secret-no-log`, which fails when a
task sends a bearer token or password over HTTP without `no_log: true` (see "Credentials and no_log").

## Molecule Quick Start

Role-local Molecule scenarios currently include:

- `apt_upgrade_register`
- `fastdeploy_register_service`
- `fastdeploy_restore`
- `nyxmon_deploy`
- `shell_basics_deploy`
- `test_dummy`
- `unifi_restore`

```bash
just molecule-test fastdeploy_register_service
just molecule-test fastdeploy_restore
just molecule-test unifi_restore
```

Molecule container names are scoped to the run, so `just test` can run from
several checkouts at once. New scenarios must name platforms
`<name>-${MOLECULE_RUN_ID:-local}`; see "Run-scoped container names" in
`TESTING.md`.

Use `just lint` only as a summary helper. It does not fail the run.
