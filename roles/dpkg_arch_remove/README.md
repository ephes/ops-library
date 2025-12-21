# Dpkg Architecture Remove Role

Remove foreign dpkg architectures (defaults to `i386`) and optionally purge packages.

## Features
- Detects configured foreign architectures and removes the requested ones.
- Guards against removing an architecture that still has installed packages.
- Optionally purges foreign-arch packages before dropping the architecture.
- Refreshes apt cache after changes (configurable).

## Variables
See `defaults/main.yml` for the full list of variables.

Common toggles:
```yaml
dpkg_arch_remove_targets:
  - i386

dpkg_arch_remove_purge_packages: false

dpkg_arch_remove_autoremove: false

dpkg_arch_remove_update_cache: true
```

## Example
```yaml
- hosts: targets
  become: true
  roles:
    - role: local.ops_library.dpkg_arch_remove
```

### Purge i386 packages automatically
```yaml
- hosts: targets
  become: true
  roles:
    - role: local.ops_library.dpkg_arch_remove
      vars:
        dpkg_arch_remove_targets:
          - i386
        dpkg_arch_remove_purge_packages: true
        dpkg_arch_remove_autoremove: true
```

## Notes
- Debian/Ubuntu only (requires dpkg).
- If any `:i386` packages are installed and `dpkg_arch_remove_purge_packages` is `false`, the role fails with a list of packages.
