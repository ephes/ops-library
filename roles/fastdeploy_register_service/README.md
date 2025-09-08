# FastDeploy Register Service Role

This Ansible role registers a service with fastDeploy for automated deployment via the web UI.

## Overview

The role sets up everything needed for fastDeploy to deploy a service using ops-control:
- Creates a deploy user with restricted permissions
- Installs runner scripts and configuration
- Sets up SOPS age keys for secret decryption
- Configures sudoers rules for secure execution
- Registers the service with fastDeploy's API

## Security Model

```
fastDeploy (runs as 'fastdeploy' user)
    ↓
    sudo (via sudoers rule)
    ↓
deploy.py (runs as 'deploy' user)
    ↓
    - Clones ops-control
    - Runs ansible-playbook
    - Has access to SOPS keys
```

## Directory Structure

After running this role, the following structure is created:

```
/Users/deploy/                        # Deploy user home
├── .config/sops/age/keys.txt        # SOPS decryption key
├── .ssh/id_ed25519                  # SSH key for git
├── runners/
│   └── nyxmon/deploy.py             # Runner script
├── ops-control/                     # Git clone workspace
└── _workspace/                      # Temp workspace

/Users/jochen/projects/fastdeploy/   # FastDeploy installation
└── services/nyxmon/config.json      # Service definition
```

## Role Variables

### Required Variables

```yaml
service_name: nyxmon                 # Name of the service to register
fd_sops_age_key_contents: "..."      # SOPS age key for decryption
```

### Optional Variables

```yaml
# FastDeploy paths
fd_fastdeploy_root: "/Users/jochen/projects/fastdeploy"
fd_fastdeploy_user: "jochen"
fd_services_root: "services"

# Deploy user
fd_deploy_user: "deploy"
fd_deploy_home: "/Users/deploy"

# Git configuration
fd_ops_control_git: "git@github.com:yourorg/ops-control.git"
fd_ops_control_ref: "main"

# API configuration
fd_api_base: "http://localhost:8000"
fd_api_token: "your-bearer-token"
```

## Example Playbook

```yaml
---
- name: Register nyxmon with fastDeploy
  hosts: macmini
  become: yes
  
  vars:
    service_name: nyxmon
    fd_sops_age_key_contents: "{{ lookup('file', '~/.config/sops/age/keys.txt') }}"
    fd_api_token: "{{ lookup('env', 'FASTDEPLOY_TOKEN') }}"
    
  tasks:
    - name: Register service
      include_role:
        name: local.ops_library.fastdeploy_register_service
```

## Usage

1. **Install the role** in your ops-library collection
2. **Configure variables** in your playbook or group_vars
3. **Run the registration**:
   ```bash
   just fastdeploy-register nyxmon macmini
   ```
4. **Verify** the service appears in fastDeploy UI
5. **Deploy** by clicking the Deploy button in the UI

## Runner Script

The deployed `deploy.py` script:
- Receives deployment context from fastDeploy via environment variables
- Clones/updates ops-control repository
- Installs Ansible collections
- Runs the deployment playbook with appropriate filters
- Reports progress back to fastDeploy API
- Verifies service status after deployment

## Security Considerations

- Deploy user has minimal privileges
- SOPS keys are readable only by deploy user (mode 0600)
- Sudoers rule is specific to the runner script path
- Environment variables are preserved for deployment context
- No secrets are stored in fastDeploy

## Troubleshooting

### Service doesn't appear in UI
- Check `config.json` was created in services directory
- Verify API token is valid
- Check fastDeploy logs for sync errors

### Deployment fails
- Check deploy user has access to ops-control repository
- Verify SOPS age key is correct
- Check ansible is installed and accessible
- Review runner script output in fastDeploy logs

### Permission denied
- Verify sudoers rule is in place
- Check file ownership and permissions
- Ensure deploy user exists