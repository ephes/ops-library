# sops_dependencies Role

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
