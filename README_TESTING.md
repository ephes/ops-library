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
- non-failing lint summary (`just lint`)
- strict Sphinx build (`just docs-build`)
- docs consistency checks (`just docs-lint`)

`just validate-strict` uses `just lint-strict` in the same sequence.

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

Use `just lint` only as a summary helper. It does not fail the run.
