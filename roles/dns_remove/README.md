# DNS Remove Role

This role removes Pi-hole and Unbound DNS services from a system, optionally restoring systemd-resolved.

## Requirements

- Ubuntu/Debian system
- Ansible 2.9+
- Root/sudo access

## Role Variables

### Required Variables

```yaml
dns_confirm_removal: true  # Must be explicitly set to confirm removal
```

### Optional Variables

```yaml
# Removal options
dns_remove_pihole_data: false  # Set to true to remove all Pi-hole data and blocklists
dns_restore_systemd_resolved: true  # Set to false to leave DNS unconfigured

# Service paths (usually auto-detected)
dns_pihole_config_dir: /etc/pihole
dns_pihole_dnsmasq_dir: /etc/dnsmasq.d
dns_unbound_config_dir: /etc/unbound/unbound.conf.d
dns_unbound_lib_dir: /var/lib/unbound
```

## Dependencies

None.

## Example Playbook

### Complete removal with data

```yaml
---
- name: Remove DNS services completely
  hosts: dns_servers
  become: true
  roles:
    - role: local.ops_library.dns_remove
      vars:
        dns_confirm_removal: true
        dns_remove_pihole_data: true
        dns_restore_systemd_resolved: true
```

### Removal preserving data

```yaml
---
- name: Remove DNS services but keep data
  hosts: dns_servers
  become: true
  roles:
    - role: local.ops_library.dns_remove
      vars:
        dns_confirm_removal: true
        dns_remove_pihole_data: false  # Preserves blocklists and data
        dns_restore_systemd_resolved: true
```

## What Gets Removed

### Always Removed
- Pi-hole services and binaries
- Unbound service and configs
- DNS firewall rules (port 53, 4711, 5335)
- Systemd service files
- Cron jobs

### Optionally Removed (when `dns_remove_pihole_data: true`)
- Pi-hole configuration directory (`/etc/pihole`)
- Pi-hole blocklists and whitelists
- Pi-hole logs
- Unbound package
- pihole user and group

### DNS Restoration
When `dns_restore_systemd_resolved: true`:
- Enables and starts systemd-resolved
- Restores `/etc/resolv.conf` symlink
- Falls back to static DNS (1.1.1.1, 8.8.8.8) if systemd-resolved unavailable

## Safety Features

- Requires explicit confirmation (`dns_confirm_removal: true`)
- Non-destructive by default (preserves data)
- Graceful handling of missing services
- Automatic systemd-resolved restoration

## Usage with dns_deploy

This role is designed to work with the `dns_deploy` role for clean redeployment:

```bash
# Remove existing DNS setup
ansible-playbook remove-dns.yml -e dns_confirm_removal=true

# Deploy fresh DNS
ansible-playbook deploy-dns.yml
```

## License

MIT

## Author Information

Created for the ops-library Ansible collection.