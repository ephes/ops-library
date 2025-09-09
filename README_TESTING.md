# Testing ops-library Services

## Important: Privacy and Security

**Never commit sensitive information like:**
- IP addresses or hostnames of your actual servers
- SSH keys or passwords
- Any internal network details

The `test/inventory.yml` file is gitignored for this reason.

## Quick Start

1. **Set up your environment:**
   ```bash
   # Create virtual environment and install dependencies
   uv venv .venv
   source .venv/bin/activate
   uv pip sync pyproject.toml
   ```

2. **Create your private inventory** (this will NOT be committed):
   ```bash
   cp test/inventory.example.yml test/inventory.yml
   # Edit test/inventory.yml with YOUR hosts (keep this file private!)
   ```

3. **Run tests:**
   ```bash
   # Test syntax only (safe, no connections)
   ./test_service.sh apt_upgrade localhost syntax
   
   # Test against your actual host (uses YOUR inventory)
   ./test_service.sh apt_upgrade your-host remote
   ```

## Test Scripts

### test_service.sh
Tests individual services with three modes:
- `syntax` - Only checks YAML/Ansible syntax (no connections)
- `local` - Runs in check mode on localhost
- `remote` - Connects to actual hosts (requires inventory)

### test_runner.sh
Comprehensive test runner that checks all services for syntax and lint issues.

## Setting Up Your Private Inventory

Create `test/inventory.yml` with YOUR hosts:

```yaml
all:
  hosts:
    localhost:
      ansible_connection: local
    
    # Add your actual hosts here (keep private!)
    my-server:
      ansible_host: 10.0.0.x  # Your actual IP
      ansible_user: myuser
      ansible_ssh_private_key_file: ~/.ssh/my_key
```

This file is gitignored and will never be committed.

## Environment Variables

Instead of hardcoding sensitive data, use environment variables:

```bash
# Set host details via environment
export ANSIBLE_HOST=your-server.local
export ANSIBLE_USER=your-user
./test_service.sh apt_upgrade my-server remote
```

## Testing Without Real Hosts

For testing without any real infrastructure:
```bash
# Syntax checks only
./test_runner.sh all

# Local testing with molecule (no VMs needed)
cd services/apt_upgrade
molecule test -s delegated
```