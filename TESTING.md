# Testing Guide for ops-library

## Overview
This guide explains how to test services and roles in the ops-library using Molecule with Docker.

## Setup

### Prerequisites
- **Python 3.11+** (3.8-3.10 no longer supported)
- uv (for virtual environment management)
- Docker (optional, only if using Docker-based tests)

> **Note:** This project follows an N-2 Python version support policy (3.11, 3.12, 3.13).

### Installation
```bash
# Create and activate virtual environment
uv venv .venv
source .venv/bin/activate

# Sync all testing dependencies from pyproject.toml
uv pip sync pyproject.toml

# Optional: Install Docker support if needed
uv pip install -e ".[docker]"

# Optional: Install Vagrant support if needed
uv pip install -e ".[vagrant]"
```

### Updating Dependencies
```bash
# To update dependencies, edit pyproject.toml then:
uv pip sync pyproject.toml

# To upgrade all packages to latest versions:
uv pip compile pyproject.toml --upgrade | uv pip sync -
```

## Testing apt_upgrade Service

### Quick Start
```bash
# Run all tests
./test_apt_upgrade.sh

# Run specific test phases
./test_apt_upgrade.sh create    # Create test containers
./test_apt_upgrade.sh converge  # Run the role
./test_apt_upgrade.sh verify    # Verify results
./test_apt_upgrade.sh destroy   # Clean up
./test_apt_upgrade.sh lint      # Run linters only
```

### Manual Testing
```bash
cd services/apt_upgrade
source ../../.venv/bin/activate

# Run full test suite
molecule test

# Run without destroying containers (for debugging)
molecule converge
molecule verify

# Connect to test container
molecule login -h ubuntu-test
```

## Test Structure

Each service should have:
```
services/<service_name>/
└── molecule/
    └── default/
        ├── molecule.yml    # Test configuration
        ├── converge.yml    # Playbook to run the service
        └── verify.yml      # Verification tests
```


### molecule.yml
Defines:
- Test platforms (Docker containers)
- Driver configuration
- Provisioner settings
- Test sequence

### converge.yml
- Runs the actual service/role
- Can include pre-tasks for setup

### verify.yml
- Verifies the service worked correctly
- Uses assertions and checks
- Should be idempotent

## Writing Tests

### Best Practices
1. **Test multiple platforms**: Include both Ubuntu and Debian
2. **Test with and without FastDeploy**: Use host_vars to test different configurations
3. **Verify idempotence**: Run twice and ensure no changes on second run
4. **Check for side effects**: Verify only expected changes occurred
5. **Test error conditions**: Include negative test cases

### Example Verification
```yaml
- name: Verify service is running
  systemd:
    name: myservice
  register: service_status
  
- name: Assert service is active
  assert:
    that:
      - service_status.status.ActiveState == "active"
    fail_msg: "Service is not running"
```

## CI/CD Integration

### GitHub Actions Example
```yaml
name: Molecule Tests
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
      - name: Install dependencies
        run: |
          pip install molecule molecule-docker ansible-lint
      - name: Run tests
        run: |
          cd services/apt_upgrade
          molecule test
```

## Troubleshooting

### Common Issues

1. **Docker permission denied**
   ```bash
   sudo usermod -aG docker $USER
   # Log out and back in
   ```

2. **Container fails to start**
   - Check Docker is running: `docker ps`
   - Check Docker daemon: `sudo systemctl status docker`

3. **Molecule can't find role**
   - Ensure correct path in converge.yml
   - Check galaxy.yml is properly configured

4. **Tests fail on idempotence**
   - Add `changed_when: false` to read-only tasks
   - Use `check_mode: no` for tasks that need to run in check mode

## Adding Tests to New Services

1. Create molecule directory structure:
   ```bash
   cd services/my_service
   molecule init scenario --driver-name docker
   ```

2. Customize molecule.yml for your platforms

3. Write converge.yml to run your service

4. Write verify.yml to check results

5. Test locally:
   ```bash
   molecule test
   ```

## Pre-commit Hooks

### Setup
```bash
# Quick setup (installs hooks and dependencies)
./setup-pre-commit.sh

# Manual setup
source .venv/bin/activate
uv pip sync pyproject.toml
pre-commit install
```

### Available Hooks
- **File checks**: Trailing whitespace, EOF fixes, large files, merge conflicts
- **YAML linting**: yamllint with custom rules
- **Ansible linting**: ansible-lint with production profile
- **Python formatting**: Black and Ruff for Python scripts
- **Shell script linting**: ShellCheck for bash scripts
- **Jinja2 linting**: Template syntax checking
- **Security**: Detect secrets and private keys
- **Markdown linting**: Documentation formatting

### Usage
```bash
# Run on all files manually
pre-commit run --all-files

# Run on specific hook
pre-commit run yamllint --all-files
pre-commit run ansible-lint --all-files

# Update hook versions
pre-commit autoupdate

# Skip hooks temporarily
git commit --no-verify -m "WIP: emergency fix"
```

## Manual Linting

If you prefer to run linters manually:
```bash
# Ansible lint
ansible-lint services/apt_upgrade/

# YAML lint
yamllint services/apt_upgrade/

# Python formatting
black services/apt_upgrade/templates/fastdeploy/*.py

# Shell script check
shellcheck *.sh

# All together via molecule
molecule lint
```

## Resources
- [Molecule Documentation](https://molecule.readthedocs.io/)
- [Ansible Testing Strategies](https://docs.ansible.com/ansible/latest/reference_appendices/test_strategies.html)
- [Docker in Molecule](https://molecule.readthedocs.io/en/latest/drivers/docker/)
