# Ops Library

A collection of reusable Ansible roles for homelab automation and service deployment.

## Roles

### fastdeploy_deploy

Deploy FastDeploy web-based deployment platform. Supports:
- Both rsync (development) and git (production) deployment methods
- PostgreSQL database setup and migrations
- Frontend build with Node.js/npm
- Python virtual environment with uv
- Systemd service configuration
- Environment-specific configuration

### fastdeploy_register_service

Register services with FastDeploy for web-based deployments. Features:
- Service configuration in FastDeploy UI
- Deployment runner script with security isolation
- Sudoers rules for cross-user execution
- SOPS integration for secrets management
- Real-time deployment progress tracking
- From-scratch deployment compatibility

### python_app_systemd

Deploy Python applications with systemd service management. Supports:
- Working tree deployment via rsync
- Virtual environment management with uv
- Django application support
- Systemd service configuration
- Optional monitoring agent setup

### test_dummy

Example service demonstrating deployment patterns. Features:
- Optional FastDeploy registration capabilities
- JSON status output for progress tracking
- Realistic deployment simulation
- Template for building other services

## Installation

### From Git (tagged release)
```yaml
# requirements.yml
collections:
  - name: https://github.com/yourusername/ops-library.git
    type: git
    version: v0.1.0
```

```bash
ansible-galaxy collection install -r requirements.yml
```

### From local directory (development)
```bash
ansible-galaxy collection install /path/to/ops-library -p ./collections
```

## Usage

See individual role documentation in `roles/*/README.md` for detailed usage instructions.

## License

MIT