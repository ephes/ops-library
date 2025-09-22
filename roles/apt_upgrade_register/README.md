# APT Upgrade Register Role

Register apt upgrade maintenance tasks with FastDeploy for remote execution.

## Description

This role sets up the necessary infrastructure for FastDeploy to execute apt upgrades remotely. It enables unprivileged services to trigger system updates through the FastDeploy API without requiring direct SSH root access. The role creates:
- Deployment scripts that FastDeploy can trigger
- Ansible playbook for performing the actual upgrades
- Sudoers configuration for secure cross-user execution
- Service configuration for FastDeploy UI
- SSH key deployment for remote server access

**Important**: This role only registers the service with FastDeploy. Actual upgrades are triggered through the FastDeploy web interface or API, not by running this role.

## Requirements

- FastDeploy must be installed and running on the target system
- Ansible must be available in the specified virtual environment
- PostgreSQL (for FastDeploy service registration)
- Python 3.8+
- Ansible 2.9+
- Required collections:
  - `ansible.posix` (for file operations)
  - `community.general` (for system tasks)

## Role Variables

### Required Variables

These variables MUST be set when using this role:

```yaml
apt_upgrade_service_name: ""  # Service identifier (e.g., "apt_upgrade_staging")
```

### Common Configuration

Frequently used settings with sensible defaults:

```yaml
# Service metadata
apt_upgrade_service_description: "System package updates via apt"
apt_upgrade_service_category: "system"

# Target configuration
apt_upgrade_target: "{{ inventory_hostname }}"  # Host to run upgrades on
apt_upgrade_target_type: "local"                # "local" or "remote"

# For remote targets only
apt_upgrade_ssh_user: "root"                    # SSH user for remote access
apt_upgrade_ssh_private_key: ""                 # SSH private key (required for remote)
```

### Advanced Configuration

```yaml
# FastDeploy integration
apt_upgrade_fastdeploy_user: "fastdeploy"
apt_upgrade_fastdeploy_home: "/home/fastdeploy"
apt_upgrade_fastdeploy_site_path: "{{ apt_upgrade_fastdeploy_home }}/site"

# Deploy user configuration
apt_upgrade_deploy_user: "deploy"
apt_upgrade_deploy_group: "{{ apt_upgrade_deploy_user }}"
apt_upgrade_deploy_home: "/home/{{ apt_upgrade_deploy_user }}"

# Ansible environment
apt_upgrade_ansible_venv: "{{ apt_upgrade_fastdeploy_home }}/ansible_venv"

# Runner paths
apt_upgrade_runner_dir: "{{ apt_upgrade_deploy_home }}/runners/{{ apt_upgrade_service_name }}"
```

For a complete list of variables, see `defaults/main.yml`.

## Dependencies

None.

## Example Playbook

### Basic Usage (Local Updates)

```yaml
- name: Register Local APT Upgrades
  hosts: deployment_server
  become: true
  roles:
    - role: local.ops_library.apt_upgrade_register
      vars:
        apt_upgrade_service_name: "apt_upgrade_local"
        apt_upgrade_target_type: "local"
```

### Advanced Usage (Remote Server Updates)

```yaml
- name: Register Remote APT Upgrades
  hosts: deployment_server
  become: true
  vars:
    ssh_keys: "{{ lookup('community.sops.sops', 'secrets/prod/deploy_ssh_keys.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.apt_upgrade_register
      vars:
        apt_upgrade_service_name: "apt_upgrade_staging"
        apt_upgrade_target: "staging.example.com"
        apt_upgrade_target_type: "remote"
        apt_upgrade_ssh_user: "root"
        apt_upgrade_ssh_private_key: "{{ ssh_keys.staging_private_key }}"
        apt_upgrade_service_description: "Staging server system updates"
```

### Multiple Server Registration

```yaml
- name: Register APT Upgrades for Multiple Servers
  hosts: deployment_server
  become: true
  vars:
    ssh_keys: "{{ lookup('community.sops.sops', 'secrets/prod/deploy_ssh_keys.yml') | from_yaml }}"
    servers:
      - name: staging
        target: staging.example.com
      - name: testing
        target: test.example.com
  tasks:
    - name: Register each server
      include_role:
        name: local.ops_library.apt_upgrade_register
      vars:
        apt_upgrade_service_name: "apt_upgrade_{{ item.name }}"
        apt_upgrade_target: "{{ item.target }}"
        apt_upgrade_target_type: "remote"
        apt_upgrade_ssh_private_key: "{{ ssh_keys[item.name + '_private_key'] }}"
      loop: "{{ servers }}"
```

## Handlers

This role does not provide any handlers.

## Tags

Available tags for selective execution:

- `apt_upgrade_ssh` - SSH key deployment tasks
- `apt_upgrade_scripts` - Script creation tasks
- `apt_upgrade_sudo` - Sudoers configuration

## Testing

```bash
# Run role tests
cd /path/to/ops-library
just test-role apt_upgrade_register

# Test the registered service
# After registration, trigger via FastDeploy UI or:
curl -X POST https://deploy.example.com/api/services/apt_upgrade_staging/deploy \
  -H "Authorization: Bearer YOUR_TOKEN"
```

## How It Works

1. **Registration Phase**: This role creates all necessary files and configurations
2. **Execution Phase**: FastDeploy triggers the registered scripts when requested
3. **Security**: Uses sudoers for privilege escalation, SSH keys for remote access
4. **Monitoring**: All executions are logged and visible in FastDeploy UI

## Security Notes

- SSH private keys are deployed with 0600 permissions
- Sudoers entries use specific command restrictions
- The deploy user has minimal privileges
- All operations are logged for audit purposes

## Changelog

- **1.0.0** (2024-09-22): Initial release with SSH key management
- See [CHANGELOG.md](../../CHANGELOG.md) for full history

## License

MIT

## Author Information

Created for homelab automation - part of the ops-library collection.