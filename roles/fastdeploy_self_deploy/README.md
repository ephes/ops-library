# FastDeploy Self-Deployment Role

This role enables FastDeploy to deploy itself, demonstrating a complete self-hosting deployment pattern that can be used as a template for other services.

## Overview

The `fastdeploy_self_deploy` role implements an in-place deployment strategy for FastDeploy, allowing it to update itself from a Git repository. This role was developed through extensive testing and debugging, and incorporates many lessons learned about subprocess communication, secrets management, and service orchestration.

## Features

- **Git-based deployment** - Pulls updates directly from GitHub repository
- **API-based progress reporting** - Direct communication with FastDeploy API (no stdout parsing)
- **In-place updates** - Simplified approach (no complex blue-green swapping)
- **SOPS integration** - Ready for encrypted secrets (currently using placeholders)
- **Self-contained runner** - Python script with graceful httpx fallback
- **UV bootstrapping** - Uses the `uv_install` role for uv provisioning

## Configuration

Key variables for uv provisioning:

- `fd_self_uv_install_dir` (default: `/usr/local/bin`)
- `fd_self_uv_binary` (default: `{{ fd_self_uv_install_dir }}/uv`)

## Architecture

```
/home/deploy/runners/fastdeploy-self/
├── runner.py           # Main deployment runner with API reporting
├── playbook.yml        # Ansible playbook for in-place updates
├── ansible.cfg         # SOPS plugin configuration
├── secrets.sops.yml    # Encrypted secrets (or placeholders)
└── requirements.txt    # Python dependencies (httpx)

/home/fastdeploy/site/services/fastdeploy-self/
├── deploy.sh          # Entry point wrapper
├── config.json        # Service metadata
└── (copies of above)  # For FastDeploy service discovery
```

## Implementation Lessons Learned

### 1. Path Handling Bug Discovery

**Problem**: FastDeploy's `Service.get_deploy_script()` was removing ALL slashes from paths:
```python
# WRONG - This broke paths like "fastdeploy-self/deploy.sh"
deploy_script = deploy_script.replace("/", "")
```

**Solution**: Fixed to handle different path types correctly:
```python
def get_deploy_script(self) -> str:
    deploy_script = self.data.get("deploy_script", "deploy.sh")
    if deploy_script.startswith("/"):
        return deploy_script  # Absolute path
    if deploy_script.startswith(f"{self.name}/"):
        return deploy_script  # Already has service prefix
    return f"{self.name}/{deploy_script}"  # Add service prefix
```

**Lesson**: Always test with paths containing slashes when dealing with service names.

### 2. Subprocess Communication Challenges

**Problem**: FastDeploy expects JSON output from deployment scripts via stdout, but:
- Ansible playbooks output extensive non-JSON text
- Parsing mixed stdout/stderr is unreliable
- Buffering issues caused deployment to appear stuck

**Initial Attempts That Failed**:
- Using `script -c` to capture output
- Wrapper scripts with exec redirection
- JSON filtering from mixed output

**Solution**: API-based progress reporting
```python
class DeploymentReporter:
    def __init__(self, config_path: Optional[str] = None):
        # Load config from secure file
        # Initialize httpx client if available
        # Fall back to stdout if no API access
    
    def emit_step(self, name: str, state: str, message: str = ""):
        # Report via API if available
        # Always emit to stdout for compatibility
```

**Lesson**: Don't fight the architecture - use the API that's already there.

### 3. Secrets Management Complexity

**Problem**: SOPS encryption added unnecessary complexity:
- Age key generation and distribution
- Ansible vault plugin configuration issues
- Encrypted values appearing in systemd units
- Permission problems between users

**What We Tried**:
- Complex SOPS-based registration playbook
- Encrypted secrets bundles
- Multiple ansible.cfg variations

**Solution**: Simplified approach with placeholder secrets:
```yaml
# secrets.sops.yml - Placeholder for now
postgres_password: changeme123
postgres_host: localhost
secret_key: changeme-secret-key
```

**Lesson**: Start simple, add encryption later when the basic flow works.

### 4. Service Registration Order

**Problem**: The complex registration playbook tried to copy `config.json` before creating it:
```yaml
# This failed because config.json didn't exist yet
- name: Copy runner files to FastDeploy services directory
  loop:
    - playbook.yml
    - ansible.cfg
    - config.json  # <-- Doesn't exist!
```

**Solution**: Use the simpler `fastdeploy_register_service` role that creates config.json properly.

**Lesson**: Test registration after clean deployment, not just in development.

### 5. Git Repository State

**Problem**: Git-based deployment with `git reset --hard` will:
- Discard all uncommitted local changes
- Lose any local configuration modifications
- Break if the directory isn't a git repository

**Solution**: Handle both cases in playbook:
```yaml
- name: Check if site directory exists
  stat:
    path: /home/fastdeploy/site/.git
  register: git_dir

- name: Initialize git repository if needed
  shell: |
    cd /home/fastdeploy/site
    git init
    git remote add origin {{ fd_self_git_repo }}
    git fetch origin
    git reset --hard origin/{{ fd_self_git_version }}
  when: not git_dir.stat.exists
```

**Lesson**: Keep local configs in `.env` files, never modify tracked files on server.

### 6. Permission Issues

**Problem**: Multiple permission-related failures:
- `/home/fastdeploy` had 750 permissions, blocking deploy user
- Log directories needed special handling
- SOPS keys required specific ownership

**Solution**: Explicit permission management:
```yaml
- name: Ensure FastDeploy home is accessible
  file:
    path: /home/fastdeploy
    mode: '0755'
```

**Lesson**: Test with multiple users, verify permissions after fresh install.

## Usage

### Registration

Register the service using the ops-control justfile:
```bash
just register-one fastdeploy-self
```

Or directly with ansible:
```bash
ansible-playbook -i inventories/prod/hosts.yml \
  playbooks/register-fastdeploy-self.yml
```

### Manual Testing

Test the runner directly:
```bash
ssh root@server "cd /home/fastdeploy/site/services/fastdeploy-self && python3 runner.py"
```

Expected output:
```json
{"name": "prepare", "state": "running", "message": "Preparing FastDeploy self-deployment"}
{"name": "prepare", "state": "success", "message": "Environment prepared"}
{"name": "deploy", "state": "running", "message": "Running Ansible playbook for self-deployment"}
{"name": "deploy", "state": "success", "message": "Deployment completed in 3.7s"}
```

### Via FastDeploy UI

1. Navigate to https://deploy.example.com
2. Find "fastdeploy-self" service
3. Click Deploy
4. Watch real-time progress

## Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `fd_self_git_repo` | `https://github.com/ephes/fastdeploy.git` | Git repository URL |
| `fd_self_git_version` | `main` | Branch/tag to deploy |
| `fd_self_deployment_mode` | `inplace` | Deployment strategy |
| `fd_self_service_name` | `fastdeploy` | Systemd service name |

## Files Structure

### runner.py
Main deployment runner with API-based progress reporting:
- Loads configuration from secure files
- Reports progress via API when available
- Falls back to stdout for compatibility
- Handles httpx import failures gracefully

### playbook.yml
Simplified in-place deployment:
- Initializes git repo if needed
- Pulls latest code
- Restarts service
- No complex blue-green swapping

### ansible.cfg
Critical SOPS configuration:
```ini
[defaults]
vars_plugins_enabled = host_group_vars,group_vars,community.sops.sops
vars_plugins = /usr/local/lib/python3.10/dist-packages/ansible_collections/community/sops/plugins/vars
```

## Common Issues and Solutions

### Issue: "Unknown step" in UI
**Cause**: Subprocess communication failure
**Solution**: Implemented API-based reporting

### Issue: Service won't start after deployment
**Cause**: Encrypted SOPS values in systemd unit
**Solution**: Ensure SOPS plugin is properly configured

### Issue: Git pull fails
**Cause**: Directory not a git repository
**Solution**: Playbook handles initialization

### Issue: Registration fails with missing config.json
**Cause**: Using complex SOPS playbook
**Solution**: Use simple registration playbook

## Testing Checklist

- [ ] Clean deployment test (remove everything, redeploy)
- [ ] Registration after fresh install
- [ ] Manual runner execution
- [ ] Deployment via UI
- [ ] Service restart verification
- [ ] Git pull with local changes
- [ ] Multiple consecutive deployments

## Security Considerations

1. **Secrets**: Currently using placeholders - implement SOPS encryption for production
2. **Git Access**: Using public HTTPS - consider SSH with deploy keys
3. **Service Restart**: Brief downtime during restart - consider health checks
4. **Local Changes**: Will be lost during deployment - document this clearly

## Future Improvements

1. **Blue-Green Deployment**: Implement zero-downtime updates
2. **Automatic Rollback**: Detect failures and revert
3. **Health Checks**: Verify service is healthy before/after
4. **Metrics**: Report deployment duration, success rate
5. **Notifications**: Alert on deployment status

## Example: Using This Pattern for Other Services

This role demonstrates patterns applicable to any self-deploying service:

1. **API-based progress reporting** instead of stdout parsing
2. **Git integration** with proper initialization handling
3. **Service discovery** via standardized directory structure
4. **Runner pattern** with configuration loading
5. **Graceful degradation** when dependencies missing

To adapt for your service:
1. Copy the role structure
2. Modify playbook.yml for your deployment needs
3. Update runner.py with your service name
4. Adjust config.json metadata
5. Test thoroughly with clean deployments

## Contributing

When modifying this role:
1. Test with `just remove-fastdeploy` first
2. Verify with `just deploy-one fastdeploy`
3. Check registration with `just register-one fastdeploy-self`
4. Test the complete flow via UI
5. Document any new pitfalls discovered

## License

Part of ops-library - See repository license.
