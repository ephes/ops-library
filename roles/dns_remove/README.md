# DNS Remove Role

This role removes Unbound DNS service from a system, optionally restoring systemd-resolved.

## Requirements

- Ubuntu/Debian system
- ansible-core 2.20+
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

1. **DDNS updater** (if configured)
   - Systemd service and timer (`ddns-update.service`, `ddns-update.timer`)
   - Update script (respects `dns_ddns_script_path`, default: `/usr/local/bin/ddns-update.sh`)
   - Configuration files (respects `dns_ddns_config_dir`, default: `/etc/ddns/`)
   - Log files (respects `dns_ddns_log_dir`, default: `/var/log/ddns/`)
   - Service account (`ddns` user)
   - **Note**: Paths are read from `dns_deploy` defaults to match deployment configuration
2. **Unbound service and packages**
3. **Configuration files** in `/etc/unbound/`
4. **Blocklist data** in `/var/lib/unbound/`
5. **Systemd timers** for blocklist updates
6. **Firewall rules** for DNS (if configured)

## Safety Features

- Requires explicit confirmation (`dns_confirm_removal: true`)
- Creates backups before removal
- Can restore systemd-resolved for continued DNS functionality
- Safe to run multiple times (idempotent)

## License

MIT

## Author

Ansible Role for DNS service removal