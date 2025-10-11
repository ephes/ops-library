# Traefik Remove Role

Ansible role to safely remove Traefik reverse proxy from a target system with options to preserve valuable data.

## Overview

This role cleanly uninstalls Traefik while providing options to preserve Let's Encrypt certificates and dynamic service configurations. It includes safety confirmation guards to prevent accidental removal.

## Features

- **Safe removal**: Requires explicit confirmation to prevent accidents
- **Selective preservation**: Preserve certificates and service configs by default
- **Clean uninstall**: Removes all Traefik components systematically
- **Idempotent**: Can be run multiple times safely
- **Clear feedback**: Shows what was removed and what was preserved

## Requirements

- ansible-core 2.15+
- Target system with Traefik installed (via `traefik_deploy` role)
- `community.general` collection (for UFW management)

## Role Variables

### Required Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `traefik_confirm_removal` | `false` | **REQUIRED**: Must be set to `true` to proceed with removal |

### Preservation Options

| Variable | Default | Description |
|----------|---------|-------------|
| `traefik_remove_preserve_certificates` | `true` | Preserve Let's Encrypt certificates for reuse |
| `traefik_remove_preserve_dynamic_configs` | `true` | Preserve dynamic service configurations |
| `traefik_remove_force_complete` | `false` | **DANGEROUS**: Remove everything including certs and configs |

### Path Configuration

These should match your `traefik_deploy` role configuration:

| Variable | Default | Description |
|----------|---------|-------------|
| `traefik_binary_path` | `/usr/local/bin/traefik` | Path to Traefik binary |
| `traefik_config_dir` | `/etc/traefik` | Traefik configuration directory |
| `traefik_static_config` | `{{ traefik_config_dir }}/traefik.toml` | Static configuration file |
| `traefik_dynamic_dir` | `{{ traefik_config_dir }}/dynamic` | Dynamic configuration directory |
| `traefik_acme_dir` | `{{ traefik_config_dir }}/acme` | ACME/Let's Encrypt directory |
| `traefik_acme_storage` | `{{ traefik_acme_dir }}/acme.json` | ACME certificate storage |
| `traefik_log_dir` | `/var/log/traefik` | Log file directory |

### Firewall Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `traefik_remove_firewall_rules` | `true` | Remove UFW firewall rules |
| `traefik_http_port` | `80` | HTTP port to remove from firewall |
| `traefik_https_port` | `443` | HTTPS port to remove from firewall |
| `traefik_dashboard_port` | `8090` | Dashboard port to remove from firewall |

### Service Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `traefik_service_name` | `traefik` | SystemD service name |

## What Gets Removed

### Always Removed

- Traefik systemd service (stopped, disabled, and unit file removed)
- Traefik binary (`/usr/local/bin/traefik`)
- Static configuration (`/etc/traefik/traefik.toml`)
- Log files (`/var/log/traefik/`)
- Logrotate configuration (`/etc/logrotate.d/traefik`)
- Temporary files (`/tmp/traefik*`)
- Firewall rules (if `traefik_remove_firewall_rules: true`)

### Preserved by Default

- Let's Encrypt certificates (`/etc/traefik/acme/`) - Allows reinstall without rate limits
- Dynamic service configs (`/etc/traefik/dynamic/`) - Services remain configured

### Parent Directory

- Configuration directory (`/etc/traefik/`) is only removed if empty after cleanup

## Usage Examples

### Example 1: Standard Removal (Recommended)

Preserve certificates and dynamic configs for easy reinstallation:

```yaml
---
- name: Remove Traefik (preserve certificates and configs)
  hosts: webserver
  become: true
  roles:
    - role: local.ops_library.traefik_remove
      vars:
        traefik_confirm_removal: true
```

**Result:**
- ✓ Service, binary, static config, logs removed
- 💾 Certificates preserved (reusable after reinstall)
- 💾 Dynamic configs preserved (services remain configured)

### Example 2: Complete Removal

Remove everything including certificates and configs:

```yaml
---
- name: Remove Traefik completely
  hosts: webserver
  become: true
  roles:
    - role: local.ops_library.traefik_remove
      vars:
        traefik_confirm_removal: true
        traefik_remove_force_complete: true
```

**Result:**
- ✓ Everything removed
- ⚠️ Certificates deleted (need to re-acquire from Let's Encrypt)
- ⚠️ Configs deleted (services need reconfiguration)

### Example 3: Keep Certificates, Remove Configs

```yaml
---
- name: Remove Traefik (keep certificates only)
  hosts: webserver
  become: true
  roles:
    - role: local.ops_library.traefik_remove
      vars:
        traefik_confirm_removal: true
        traefik_remove_preserve_certificates: true
        traefik_remove_preserve_dynamic_configs: false
```

### Example 4: Skip Firewall Cleanup

If your system doesn't use UFW or you want to keep firewall rules:

```yaml
---
- name: Remove Traefik (skip firewall)
  hosts: webserver
  become: true
  roles:
    - role: local.ops_library.traefik_remove
      vars:
        traefik_confirm_removal: true
        traefik_remove_firewall_rules: false
```

## Integration with ops-control

### Using Justfile Command

```bash
# Standard removal (preserve certs & configs)
just remove-one traefik

# Complete removal
just remove-one traefik --complete

# Remove certs but keep configs
just remove-one traefik --no-certs

# Remove configs but keep certs
just remove-one traefik --no-configs
```

### Direct Ansible Playbook

```bash
# Standard removal
ansible-playbook -i inventory playbooks/remove-traefik.yml \
  -e traefik_confirm_removal=true

# Complete removal
ansible-playbook -i inventory playbooks/remove-traefik.yml \
  -e traefik_confirm_removal=true \
  -e traefik_remove_force_complete=true
```

## Safety Confirmation

By default, the role will fail with a detailed warning message if `traefik_confirm_removal` is not explicitly set to `true`. This prevents accidental removal.

**Warning message includes:**
- List of components that will be removed
- List of components that will be preserved
- Impact on services using Traefik
- Instructions for proceeding

## Reinstalling After Removal

If you preserved certificates and configs (default behavior):

```bash
# Reinstall Traefik - will reuse existing certificates
just deploy-one traefik
```

Services will automatically reconnect to Traefik using preserved dynamic configurations.

## Impact on Services

**⚠️ WARNING**: Removing Traefik will make all services using it **inaccessible via HTTPS** until Traefik is reinstalled.

Affected services may include:
- FastDeploy
- Nyxmon
- Home Assistant
- Paperless
- Any service with Traefik dynamic configuration

## Dependencies

This role has no dependencies on other roles, but it's designed to work with:
- `traefik_deploy` - Deploys Traefik (paths must match)
- Service-specific remove roles should clean their own dynamic configs

## Tags

You can run specific parts of the removal:

```bash
# Only validate (show what would be removed)
ansible-playbook playbooks/remove-traefik.yml --tags validate

# Only remove service
ansible-playbook playbooks/remove-traefik.yml --tags service

# Skip firewall cleanup
ansible-playbook playbooks/remove-traefik.yml --skip-tags firewall
```

Available tags:
- `validate` - Safety checks and confirmation
- `service` - SystemD service removal
- `binary` - Binary removal
- `config` - Configuration file removal
- `logs` - Log file cleanup
- `firewall` - Firewall rule removal
- `cleanup` - Temporary file cleanup

## Idempotency

This role is fully idempotent and can be run multiple times safely. It will:
- Skip removal of files that don't exist
- Not fail if service is already stopped
- Handle missing firewall rules gracefully

## Rollback / Recovery

If removal was accidental:

1. **Reinstall Traefik**: `just deploy-one traefik`
2. **If certificates preserved**: Traefik reuses them automatically
3. **If configs preserved**: Services reconnect automatically
4. **If certificates deleted**: Let's Encrypt issues new ones (may hit rate limits)
5. **If configs deleted**: Re-deploy affected services

## Security Considerations

### Let's Encrypt Certificates
- Rate limited: 5 certificates per week per domain
- Default: PRESERVE (safe for reinstallation)
- Contains public certificates only (no sensitive data)

### Dynamic Configurations
- May contain service URLs and routing rules
- No secrets stored (credentials are in services)
- Default: PRESERVE (allows service remove roles to clean up)

### Firewall Rules
- Removing closes ports 80/443
- Prevents HTTP/HTTPS access
- Default: REMOVE (security-first approach)

### Log Files
- May contain access logs with IP addresses
- Default: REMOVE

## Testing

The role can be tested using Ansible's check mode:

```bash
# Dry run (check mode)
ansible-playbook playbooks/remove-traefik.yml --check \
  -e traefik_confirm_removal=true
```

## Troubleshooting

### Role fails with "removal not confirmed"
**Solution**: Set `traefik_confirm_removal: true` in your playbook or via `-e`

### Services still inaccessible after reinstall
**Cause**: Dynamic configs were removed
**Solution**: Re-deploy affected services to regenerate Traefik configs

### Certificate errors after reinstall
**Cause**: Certificates were removed
**Solution**: Wait for Let's Encrypt to issue new certificates (automatic)

### Firewall rules not removed
**Cause**: UFW not installed or `traefik_remove_firewall_rules: false`
**Solution**: Manually remove rules or ensure UFW is installed

## License

MIT

## Author

Created for ops-library collection
