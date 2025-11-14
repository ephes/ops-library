# CLAUDE.md - AI Assistant Context for ops-library

## Project Overview

**ops-library** is a public Ansible collection containing reusable automation roles for homelab services. This collection provides the deployment logic, while secrets and environment-specific configuration are managed separately in private control repositories like ops-control.

## Key Documentation

### Primary Documentation
- **[README.md](./README.md)** - Quick start guide and role overview table
- **[ARCHITECTURE.md](./ARCHITECTURE.md)** - Detailed system design, principles, and patterns

### How-To Guides
- **[Service Lifecycle Guide](./docs/source/howto/service_lifecycle.md)** - Step-by-step checklist for creating deploy/backup/restore/remove roles plus ops-control integration.

### Role Documentation
Each role has comprehensive documentation in its README:
- Service deployment roles: `roles/*_deploy/README.md`
- Service removal roles: `roles/*_remove/README.md`
- Registration roles: `roles/*_register/README.md`
- Bootstrap roles: `roles/*_install/README.md`

### Testing Documentation
- **[TESTING.md](./TESTING.md)** - Comprehensive testing guidelines
- **[README_TESTING.md](./README_TESTING.md)** - Quick testing reference

## Design Principles

1. **No Secrets**: This is a PUBLIC repository - never include real secrets, passwords, or API keys
2. **Safe Defaults**: Use "CHANGEME" placeholders that are validated and rejected at runtime
3. **Idempotency**: All roles must be safely runnable multiple times
4. **Documentation**: Every role must have a comprehensive README with examples
5. **Testing**: Integration tests for critical functionality

## Collection Structure

```
local.ops_library (namespace.name)
├── roles/
│   ├── fastdeploy_deploy/      # Deploy FastDeploy platform
│   ├── nyxmon_deploy/          # Deploy Nyxmon monitoring
│   ├── apt_upgrade_register/   # Register apt upgrades with FastDeploy
│   ├── uv_install/             # Install uv for Python
│   └── ...
```

## Development Workflow

1. **Make changes** to roles in this repository
2. **Test locally** using the test framework
3. **Build collection**: `ansible-galaxy collection build .`
4. **Install in ops-control**: `cd ../ops-control && just install-local-library`
5. **Deploy and test**: Use ops-control commands to deploy

## Quick Reference

### Build and Install
```bash
# Build the collection
ansible-galaxy collection build .

# Install to ops-control
cd ../ops-control
just install-local-library
```

### Run Tests
```bash
# All tests
just test

# Specific role
just test-role fastdeploy_deploy
```

### Create New Role
```bash
# Use ansible-galaxy or manually create structure
ansible-galaxy role init roles/servicename_deploy

# Required structure:
roles/servicename_deploy/
├── defaults/main.yml    # ALL variables with safe defaults
├── tasks/main.yml       # Main task orchestration
├── templates/*.j2       # Config templates
├── handlers/main.yml    # Service handlers
└── README.md           # COMPREHENSIVE documentation
```

## Important Notes

- **Public Repository**: Review all changes for sensitive information
- **Variable Validation**: All secrets must be validated with assert tasks
- **Documentation First**: Update role README before implementation
- **Test Coverage**: Add tests for new functionality
- **Semantic Versioning**: Update galaxy.yml version appropriately

## Related Projects

- **ops-control**: Private control repository (inventories, secrets, playbooks)
- **FastDeploy**: Web-based deployment platform
- **Nyxmon**: Monitoring service with Telegram integration
