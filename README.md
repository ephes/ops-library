# Ops Library

A collection of reusable Ansible roles for homelab automation and service deployment.

## Roles

### python_app_systemd

Deploy Python applications with systemd service management. Supports:
- Working tree deployment via rsync
- Virtual environment management with uv
- Django application support
- Systemd service configuration
- Optional monitoring agent setup

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