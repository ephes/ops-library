# Ops Library Documentation

A collection of reusable Ansible roles for homelab automation and service deployment.

```{toctree}
:maxdepth: 2
:caption: Contents

architecture
testing
roles/index
changelog
```

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

The ops-library collection provides reusable Ansible roles organized by category:

- **{doc}`Deployment Roles <roles/deployment/index>`** - Deploy services like FastDeploy, Nyxmon, and Traefik
- **{doc}`Removal Roles <roles/removal/index>`** - Safely remove deployed services
- **{doc}`Registration Roles <roles/registration/index>`** - Register services with FastDeploy
- **{doc}`Bootstrap Roles <roles/bootstrap/index>`** - Install required tools and dependencies
- **{doc}`Testing Roles <roles/testing/index>`** - Development and testing utilities

See the {doc}`complete role catalog <roles/index>` for details on each role.

## Key Features

- **No Secrets**: Public repository with safe defaults and runtime validation
- **Idempotent**: All roles can be safely run multiple times
- **Well-Documented**: Comprehensive README for every role
- **Tested**: Integration tests for critical functionality
- **Modular**: Use individual roles or combine them

## Requirements

- Ansible 2.9+
- Python 3.8+
- Collections: `community.general`, `ansible.posix`

## Development

```bash
# Run all tests
just test

# Test specific role
just test-role fastdeploy_deploy

# Install pre-commit hooks
just install-hooks
```

## Documentation

- {doc}`architecture` - System design and patterns
- {doc}`testing` - Testing guidelines
- {doc}`roles/index` - Complete role reference
- {doc}`changelog` - Version history

## License

MIT
