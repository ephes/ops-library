# UV Install Role

Install and manage the Astral uv package manager with proper self-update support.

## Features

- Installs uv to user's `.local/bin` directory (preserves self-update capability)
- Creates system-wide symlinks for easy access
- Supports updating existing installations
- Verifies installation and self-update functionality

## Requirements

- curl
- bash

## Role Variables

```yaml
# Version to install (latest, or specific like "0.8.15")
uv_version: latest

# Installation directory (user's local bin)
uv_install_dir: "/root/.local/bin"

# System-wide symlink location
uv_symlink_dir: "/usr/local/bin"

# Whether to create system-wide symlinks
uv_create_symlinks: true

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