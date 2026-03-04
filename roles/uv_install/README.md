# UV Install Role

Install and manage the Astral uv package manager.

## Features

- Installs uv into a configurable system path (default `/usr/local/bin`)
- Supports explicit owner/group for cross-platform compatibility (`root:wheel` on macOS)
- Optionally creates system-wide symlinks for compatibility
- Supports updating existing installations
- Verifies installation and basic functionality

## Requirements

- curl
- bash

## Role Variables

```yaml
# Version to install (latest, or specific like "0.8.15")
uv_version: latest

# Installation directory
uv_install_dir: "/usr/local/bin"

# File ownership for installed binaries
uv_install_owner: "root"
uv_install_group: "{{ 'wheel' if ansible_facts.os_family == 'Darwin' else 'root' }}"

# System-wide symlink location
uv_symlink_dir: "/usr/local/bin"

# Whether to create system-wide symlinks
uv_create_symlinks: false

# Whether to update if already installed
uv_update_existing: true
```

## Example Playbook

```yaml
- hosts: servers
  roles:
    - role: local.ops_library.uv_install
      vars:
        uv_version: latest
        uv_create_symlinks: true
```

## Usage in Deployment Roles

UV is typically used as a dependency in service deployment roles:

```yaml
# In your custom deployment role's meta/main.yml
dependencies:
  - role: local.ops_library.uv_install

# Or in a playbook
- name: Deploy Python service
  hosts: servers
  roles:
    - role: local.ops_library.uv_install
    - role: local.ops_library.myservice_deploy
```

## License

MIT
