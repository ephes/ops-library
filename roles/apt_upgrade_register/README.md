# apt_upgrade_register

Register apt upgrade maintenance tasks with FastDeploy for remote execution.

## Description

This role sets up the necessary infrastructure for FastDeploy to execute apt upgrades remotely. It creates:
- Deployment scripts that FastDeploy can trigger
- Ansible playbook for performing the actual upgrades
- Sudoers configuration for secure execution
- Service configuration for FastDeploy UI

**Important**: This role only registers the service with FastDeploy. Actual upgrades are triggered through the FastDeploy web interface, not by running this role.

## Requirements

- FastDeploy must be installed and configured on the target system
- Ansible must be available in the specified virtual environment
- The deploy user must exist or will be created

## Role Variables

### Required Variables

```yaml
apt_upgrade_service_name: ""  # Name of the service (e.g., "apt_upgrade_local")
```

### Optional Variables

```yaml
# Service description
apt_upgrade_service_description: "System package updates via apt"

# FastDeploy configuration
apt_upgrade_fastdeploy_user: fastdeploy
apt_upgrade_fastdeploy_home: /home/fastdeploy
apt_upgrade_fastdeploy_site_path: "{{ apt_upgrade_fastdeploy_home }}/site"
apt_upgrade_service_path: "{{ apt_upgrade_fastdeploy_site_path }}/services/{{ apt_upgrade_service_name }}"

# Deploy user configuration
apt_upgrade_deploy_user: deploy
apt_upgrade_deploy_group: "{{ apt_upgrade_deploy_user }}"

# Ansible configuration
apt_upgrade_ansible_venv: "{{ apt_upgrade_fastdeploy_home }}/ansible_venv"

# Target configuration
apt_upgrade_target: "{{ inventory_hostname }}"  # Target host for upgrades
apt_upgrade_target_type: "local"  # "local" or "remote"

# APT upgrade options
apt_upgrade_cache_valid_time: 3600
apt_upgrade_update_cache: true
apt_upgrade_dist_upgrade: true
apt_upgrade_auto_clean: true
apt_upgrade_auto_remove: true
apt_upgrade_reboot_if_required: false

# FastDeploy integration
apt_upgrade_dynamic_steps: true
```

## Example Playbook

### Register apt_upgrade for local execution (on macmini itself)

```yaml
---
- name: Register apt_upgrade_local with FastDeploy
  hosts: macmini
  become: true
  roles:
    - role: local.ops_library.apt_upgrade_register
      vars:
        apt_upgrade_service_name: "apt_upgrade_local"
        apt_upgrade_target: "localhost"
        apt_upgrade_target_type: "local"
        apt_upgrade_service_description: "System updates for macmini"
```

### Register apt_upgrade for remote execution (staging server)

```yaml
---
- name: Register apt_upgrade_staging with FastDeploy
  hosts: macmini  # FastDeploy runs here
  become: true
  roles:
    - role: local.ops_library.apt_upgrade_register
      vars:
        apt_upgrade_service_name: "apt_upgrade_staging"
        apt_upgrade_target: "staging.example.com"
        apt_upgrade_target_type: "remote"
        apt_upgrade_service_description: "System updates for staging server"
        # Note: SSH keys must be configured separately for remote access
```

## How It Works

1. **Registration**: Running this role creates the FastDeploy runner infrastructure
2. **Execution**: Users trigger upgrades through FastDeploy web UI
3. **Process Flow**:
   ```
   FastDeploy UI → deploy.sh → deploy.py → ansible-playbook → apt upgrades
   ```

## Security Considerations

- The role creates specific sudoers entries for the deploy user
- Only allows execution of apt-related commands
- Reboot permission is conditional based on `apt_upgrade_reboot_if_required`
- For remote targets, SSH keys must be manually configured

## Migration from site.yml

This role replaces the complex `site.yml → manifest → system role → services/apt_upgrade` flow with a simple registration pattern that follows the FastDeploy architecture.

## License

See main collection license.

## Author Information

Created as part of the site.yml migration project.