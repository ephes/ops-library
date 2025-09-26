# DNS Remove Role

This role removes Unbound DNS service from a system, optionally restoring systemd-resolved.

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
dns_restore_systemd_resolved: true  # Set to false to leave DNS unconfigured

# Service paths (usually auto-detected)
dns_unbound_config_dir: /etc/unbound/unbound.conf.d
dns_unbound_lib_dir: /var/lib/unbound
```

## Dependencies

None.

## Example Playbook

### Complete removal

```yaml
---
- name: Remove DNS services
  hosts: dns_servers
  become: true
  roles:
    - role: local.ops_library.dns_remove
      vars:
        dns_confirm_removal: true
        dns_restore_systemd_resolved: true
```

### Remove without restoring systemd-resolved

```yaml
---
- name: Remove DNS but keep custom resolver
  hosts: dns_servers
  become: true
  roles:
    - role: local.ops_library.dns_remove
      vars:
        dns_confirm_removal: true
        dns_restore_systemd_resolved: false
```

## What Gets Removed

1. **Unbound service and packages**
2. **Configuration files** in `/etc/unbound/`
3. **Blocklist data** in `/var/lib/unbound/`
4. **Systemd timers** for blocklist updates
5. **Firewall rules** for DNS (if configured)

## Safety Features

- Requires explicit confirmation (`dns_confirm_removal: true`)
- Creates backups before removal
- Can restore systemd-resolved for continued DNS functionality
- Safe to run multiple times (idempotent)

## License

MIT

## Author

Ansible Role for DNS service removal