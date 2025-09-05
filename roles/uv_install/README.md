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

## Usage in Service Manifests

```yaml
# ops-control/services.d/python-app.yml
service:
  name: myapp
  host: server1
  role: local.ops_library.python_app_systemd
  dependencies:
    - local.ops_library.uv_install  # Ensure uv is installed first
```

## License

MIT