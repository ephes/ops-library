# Role Name

One-line description of what this role does.

## Description

Detailed description of the role's purpose, features, and what it manages. Include key capabilities and any important behaviors.

## Requirements

- System requirements (OS, packages, services)
- Ansible version requirements
- Required Ansible collections
- Any prerequisite roles or configurations

## Role Variables

### Required Variables

These variables MUST be set when using this role:

```yaml
role_required_var1: ""  # Description of variable
role_required_var2: ""  # Generate with: command to generate
```

### Common Configuration

Frequently used variables with sensible defaults:

```yaml
role_common_var1: "default_value"  # Description
role_common_var2: 8080             # Port number
```

### Advanced Configuration

Less commonly modified variables:

```yaml
role_advanced_var1: "/path/to/something"
role_advanced_var2: true
```

For a complete list of variables, see `defaults/main.yml`.

## Dependencies

List any role dependencies or `None` if standalone.

## Example Playbook

### Basic Usage

```yaml
- name: Deploy Service
  hosts: target_hosts
  become: true
  vars:
    role_required_var1: "value"
    role_required_var2: "{{ encrypted_secret }}"
  roles:
    - role: local.ops_library.role_name
```

### Advanced Usage

```yaml
- name: Deploy with Custom Configuration
  hosts: target_hosts
  become: true
  vars:
    sops_secrets: "{{ lookup('community.sops.sops', 'secrets/prod/service.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.role_name
      vars:
        role_required_var1: "{{ sops_secrets.key1 }}"
        role_common_var1: "custom_value"
```

## Handlers

This role provides the following handlers:

- `handler_name` - Description of what triggers this handler

## Tags

Available tags for selective execution:

- `tag1` - Description
- `tag2` - Description

## Testing

```bash
# Run role tests
cd /path/to/ops-library
just test-role role_name
```

## Changelog

- **1.0.0** (2024-09-22): Initial release
- See [CHANGELOG.md](../../CHANGELOG.md) for full history

## License

MIT

## Author Information

Your Name - your.email@example.com