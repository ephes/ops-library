# FastDeploy Service Registration Role

This role registers services with FastDeploy for web-based git deployments, enabling services to be deployed through the FastDeploy UI with real-time progress tracking.

## Overview

The `fastdeploy_register_service` role creates a complete FastDeploy service registration, including:

- Service configuration in FastDeploy UI
- Deployment runner script with proper security isolation
- Sudoers rules for cross-user execution
- SOPS integration for secrets management
- Real-time deployment progress tracking

## Key Features

✅ **Custom Script Support**: Use `fd_runner_content` to provide simple deployment scripts
✅ **Proper Security Model**: Multi-user execution with `fastdeploy` → `deploy` user isolation  
✅ **Real-time Progress**: JSON status output for FastDeploy UI progress tracking
✅ **Configuration Handling**: Automatic parsing of FastDeploy's config structure
✅ **From-scratch Compatible**: Works correctly when redeploying entire infrastructure
✅ **Unified Commands**: Integrates with `just register-one service-name` pattern

## Complete Example

The `test_dummy` service demonstrates all features and serves as a template for other services.

### Registration Playbook
```yaml
# playbooks/register-test-dummy-proper.yml
- name: Register test_dummy service with FastDeploy
  hosts: macmini
  become: true
  tasks:
    - name: Register test_dummy service
      include_role:
        name: local.ops_library.fastdeploy_register_service
      vars:
        fd_service_name: "test_dummy"
        fd_service_description: "Example deployment service demonstrating FastDeploy best practices"
        
        # Custom deployment script content
        fd_runner_content: |
          #!/usr/bin/env python3
          import json, time, sys, argparse
          from pathlib import Path
          
          def emit_step(name, state, message=""):
              print(json.dumps({"name": name, "state": state, "message": message}), flush=True)
          
          def main():
              parser = argparse.ArgumentParser()
              parser.add_argument('--config', help='Configuration file path')
              args = parser.parse_args()
              
              config = {}
              if args.config and Path(args.config).exists():
                  with open(args.config, 'r') as f:
                      config = json.load(f)
              
              # Extract service name from FastDeploy's deploy_script path
              deploy_script = config.get('deploy_script', '')
              service_name = deploy_script.split('/')[0] if '/' in deploy_script else 'test_dummy'
              
              emit_step("Initialize deployment", "success", f"Starting deployment for {service_name}")
              
              steps = ["Validate environment", "Install dependencies", "Configure service", "Start service"]
              for step in steps:
                  emit_step(step, "running", f"Executing: {step}")
                  time.sleep(2)  # Simulate work
                  emit_step(step, "success", f"Completed: {step}")
              
              return 0
          
          if __name__ == "__main__":
              sys.exit(main())
```

### Usage
```bash
# Register the service
just register-one test-dummy

# Test deployment
./scripts/test_deployment.py --service test_dummy

# Deploy via FastDeploy web UI
# Navigate to https://your-fastdeploy-instance/
```

## FastDeploy Script Requirements

### 1. Configuration Handling
FastDeploy passes a `--config` parameter with this JSON structure:
```json
{
  "deployment_id": "deploy_123",
  "access_token": "jwt_token", 
  "deploy_script": "service_name/deploy.py",
  "steps_url": "https://host/steps/",
  "deployment_finish_url": "https://host/deployments/finish/",
  "context": {"env": {}},
  "path_for_deploy": "/usr/bin:/bin"
}
```

Extract service name: `service_name = config.get('deploy_script', '').split('/')[0]`

### 2. JSON Status Output
```python
def emit_step(name, state, message=""):
    step_data = {"name": name, "state": state}
    if message:
        step_data["message"] = message  
    print(json.dumps(step_data), flush=True)

# States: "running", "success", "failure"
emit_step("Install packages", "running", "Installing dependencies...")
emit_step("Install packages", "success", "All packages installed")
```

### 3. Exit Codes
- Return `0` for success
- Return non-zero for failure
- Handle exceptions gracefully

## Role Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `fd_service_name` | *required* | Service name |
| `fd_service_description` | `"Deploy {service} via ops-control"` | Description for FastDeploy UI |
| `fd_runner_content` | `""` | Custom script content (overrides default template) |
| `fd_fastdeploy_user` | `"fastdeploy"` | FastDeploy service user |
| `fd_deploy_user` | `"deploy"` | Deployment execution user |

## Architecture

### File Locations
```
/home/fastdeploy/site/services/{service}/
├── config.json          # Service metadata for FastDeploy UI
└── deploy.py            # Deployment script (FastDeploy calls this)

/home/deploy/runners/{service}/  
└── deploy.py            # Source deployment script

/etc/sudoers.d/fastdeploy_{service}  # Sudoers rules
```

### Security Model
1. **FastDeploy** (fastdeploy user) receives web requests
2. **Creates secure config** in `/var/tmp/` with deployment parameters  
3. **Uses sudo** to execute script as `deploy` user
4. **Deploy user** runs script with restricted permissions

## From-Scratch Compatibility

✅ **The role now properly handles from-scratch deployments** by:

1. **Creating script in both locations**:
   - `/home/deploy/runners/{service}/deploy.py` (source)  
   - `/home/fastdeploy/site/services/{service}/deploy.py` (FastDeploy calls this)

2. **Updating config.json** to reference `deploy.py` (relative path)

3. **Maintaining sync** between both script locations

This means when you remove the fastdeploy user and redeploy everything, the service registration will work correctly without manual intervention.

## Integration with ops-control

Works seamlessly with the unified command pattern:
```bash
just register-one test-dummy    # Uses register-test-dummy-proper.yml
just register-one fastdeploy-self  # Uses register-fastdeploy-self.yml  
just register-one new-service  # Shows available services if not found
```

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