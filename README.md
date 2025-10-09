# Ops Library

A collection of reusable Ansible roles for homelab automation and service deployment.

📚 **[Architecture Documentation](./ARCHITECTURE.md)** - Detailed design and implementation patterns

## Quick Start

```bash
# Build and install the collection locally
ansible-galaxy collection build .
ansible-galaxy collection install local-ops_library-*.tar.gz -p ../ops-control/collections

# Or use from ops-control
cd ../ops-control
just install-local-library
```

## Available Roles

The table below links each published role to its dedicated documentation. Refer to the role README for full variable reference, workflows, and examples.

| Category | Role | Summary |
|----------|------|---------|
| Infrastructure | [`traefik_deploy`](roles/traefik_deploy/README.md) | Deploy Traefik reverse proxy with Let's Encrypt (auto-detects platform, version upgrades). |
| Service deployment | [`fastdeploy_deploy`](roles/fastdeploy_deploy/README.md) | Deploy the FastDeploy platform (database, uv, frontend build, systemd, Traefik). |
| Service deployment | [`nyxmon_deploy`](roles/nyxmon_deploy/README.md) | Deploy Nyxmon (Django app, monitoring agent, Telegram integration). |
| Service removal | [`fastdeploy_remove`](roles/fastdeploy_remove/README.md) | Remove FastDeploy and related resources safely. |
| Service removal | [`nyxmon_remove`](roles/nyxmon_remove/README.md) | Remove Nyxmon while preserving data as needed. |
| Service registration | [`apt_upgrade_register`](roles/apt_upgrade_register/README.md) | Register apt-upgrade maintenance runners with FastDeploy. |
| Service registration | [`fastdeploy_register_service`](roles/fastdeploy_register_service/README.md) | Generic FastDeploy service registration helper. |
| Bootstrap | [`ansible_install`](roles/ansible_install/README.md) | Ensure controller has Ansible and required plugins. |
| Bootstrap | [`uv_install`](roles/uv_install/README.md) | Install uv for Python environment management. |
| Bootstrap | [`sops_dependencies`](roles/sops_dependencies/README.md) | Install age/SOPS prerequisites. |
| Testing/demo | [`test_dummy`](roles/test_dummy/README.md) | Demonstration service for developing and testing runners. |

## Development

### Testing
```bash
# Run all tests
just test

# Test specific role
just test-role fastdeploy_deploy
just test-role traefik_deploy

# Or run test playbooks directly
ansible-playbook tests/test_traefik_deploy.yml -i tests/inventory/test.yml
```

### Pre-commit Hooks
```bash
# Install pre-commit hooks
just install-hooks
```

## Documentation

- [ARCHITECTURE.md](./ARCHITECTURE.md) - System design and patterns
- [CHANGELOG.md](./CHANGELOG.md) - Version history and changes
- [TESTING.md](./TESTING.md) - Testing guidelines
- [Role-specific READMEs](./roles/) - Detailed documentation per role
- [README_TEMPLATE.md](./roles/README_TEMPLATE.md) - Template for role documentation

## Requirements

- Ansible 2.9+
- Python 3.8+
- Collections: `community.general`, `ansible.posix`

## License

MIT
