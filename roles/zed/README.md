# zed Role

ZFS Event Daemon (ZED) configuration with email notifications and scrub scheduling.

## Description

This role configures ZED for ZFS event notifications. It sets up email alerts for pool state changes (DEGRADED, FAULTED), scrub completions/errors, checksum errors, and device failures. Optionally, it creates systemd timers for scheduled pool scrubs.

## Requirements

- Debian/Ubuntu with `systemd` and ZFS installed
- Root privileges
- A working mail relay for email alerts (see `mail_relay_client` role)

## Role Variables

### Required

```yaml
zed_email_to: "admin@example.com"  # Email recipient for ZFS alerts
```

### Optional

```yaml
zed_enabled: true                              # Enable/disable the role
zed_email_prog: "mail"                         # Mail program for alerts

zed_rc_path: "/etc/zfs/zed.d/zed.rc"           # ZED config path
zed_packages:
  - zfs-zed
zed_service_name: "zfs-zed"

# Scrub scheduling
zed_manage_scrub_timer: true                   # Create scrub timers
zed_scrub_pools: []                            # List of pools to scrub
zed_scrub_timer_on_calendar: "weekly"          # Scrub frequency
zed_scrub_timer_randomized_delay_sec: "6h"     # Random delay to spread load
```

See `defaults/main.yml` for the full list.

## Example Playbook

```yaml
- name: Configure ZED notifications
  hosts: zfs_servers
  become: true
  roles:
    - role: local.ops_library.zed
      vars:
        zed_email_to: "root"
        zed_scrub_pools:
          - fast
          - tank
```

## Handlers

- `Restart zed` – Restarts the zfs-zed service when configuration changes
- `Reload systemd` – Reloads systemd after timer/service file changes

## Tags

- `zed` – run all tasks in this role

## Testing

```bash
# From repo root
just test-role zed

# Verify on target host
systemctl status zfs-zed
grep ZED_EMAIL /etc/zfs/zed.d/zed.rc
systemctl list-timers | grep zpool

# Test ZED (generates a test event)
zpool scrub <pool>
```

## Changelog

- **1.0.0** (2025-12-14): Initial release

## License

MIT

## Author Information

Jochen Wersdoerfer
