# SOPS Dependencies Role

Ensures the controller or target host has the tooling required for SOPS-encrypted secrets.

## Features
- Installs the `age` tool used for key management.
- Installs Mozilla `sops` binary.
- Optionally verifies the binaries are executable and on the expected PATH.

## Variables
See `defaults/main.yml` for platform-specific package names and feature flags (e.g. `sops_install_from_brew`).

## Example
```yaml
- hosts: controller
  become: true
  roles:
    - role: local.ops_library.sops_dependencies
```

## Notes
- Run this role before attempting any SOPS lookups in playbooks.

## Verified release downloads

The binary installation paths remain `/usr/local/bin/sops`, `/usr/local/bin/age` and `/usr/local/bin/age-keygen`; downloads remain Linux amd64. Both sops download paths (apt fallback and binary mode) verify SHA-256. The apt fallback still installs only when sops is absent; binary mode reconciles the pinned sops and age binaries. Apt and snap package handling is unchanged.

Pinned defaults (checksum map keys identify the release architecture/target):

| Variable | Default |
| --- | --- |
| `sops_deps_age_version` | `1.3.2` |
| `sops_deps_sops_version` | `3.13.3` |
| `sops_deps_sops_checksum` | `sha256:e5bec3346a873ae91d871550f3e698c1aad962aff462a080e40f25fde17fef6b` |
| `sops_deps_age_checksum` | `sha256:cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10` |

To update, bump the version and checksum together. Fetch the SHA-256 from the
project’s published checksum file or release-page asset digest over HTTPS,
and update the source URL comment beside the checksum in `defaults/main.yml`.
Never reuse the old checksum for a new version. Supply matching checksums for
every enabled architecture. Run `just test-root-downloads` before deploying.
