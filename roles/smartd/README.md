# smartd Role

SMART disk monitoring with smartmontools for HDD and NVMe drives.

## Description

This role installs and configures `smartmontools` for disk health monitoring. It supports both traditional SATA/SAS disks and NVMe SSDs, with configurable temperature thresholds and email alerts. Regular SMART self-tests are scheduled automatically.

## Requirements

- Debian/Ubuntu with `systemd`
- Root privileges
- A working mail relay for email alerts (see `mail_relay_client` role)

## Role Variables

### Required

```yaml
smartd_devices:
  - device: /dev/disk/by-id/ata-WDC_WD120EFGX-68CPHN0_WD-B00MJ7WD
    type: ata
    name: tank-hdd-1
    smartd_no_spinup: true
  - device: /dev/disk/by-id/nvme-Samsung_SSD_980_PRO_1TB_S5GXNX0T308527F
    type: nvme
    name: boot-nvme

smartd_mail_to: "admin@example.com"  # Email recipient for alerts
```

### Optional

```yaml
smartd_enabled: true                  # Enable/disable the role
smartd_mail_from: "root"              # Email sender
smartd_manage_service: true           # Manage smartd service
smartd_opts: ""                       # Extra smartd daemon options (e.g., "--interval=7200")

# Temperature thresholds (smartd -W DIFF,INFO,CRIT)
smartd_temp_diff: 4                   # Delta to trigger warning
smartd_temp_info: 40                  # Info threshold (°C)
smartd_temp_crit: 45                  # Critical threshold (°C)

# Self-test schedules (smartd regex format)
smartd_short_test_schedule: "S/../.././02"   # Daily at 2am
smartd_long_test_schedule: "L/../../6/03"    # Saturdays at 3am

smartd_config_path: "/etc/smartd.conf"
smartd_packages:
  - smartmontools
  - nvme-cli
smartd_service_name: "smartmontools"
```

Per-device optional fields:
```yaml
smartd_devices:
  - device: /dev/disk/by-id/ata-WDC_WD120EFGX-68CPHN0_WD-B00MJ7WD
    type: sat
    name: tank-hdd-1
    smartd_no_spinup: true  # Adds "-n standby" to avoid waking sleeping disks
    smartd_short_test_schedule: "S/../../0/06"  # Override short test schedule
    smartd_long_test_schedule: "L/../../0/07"   # Override long test schedule
```

See `defaults/main.yml` for the full list.

## Example Playbook

```yaml
- name: Configure SMART monitoring
  hosts: storage_servers
  become: true
  roles:
    - role: local.ops_library.smartd
      vars:
        smartd_mail_to: "alerts@example.com"
        smartd_devices:
          - device: /dev/disk/by-id/ata-WDC_WD120EFGX-68CPHN0_WD-B00MJ7WD
            type: ata
            name: tank-hdd-1
          - device: /dev/disk/by-id/nvme-Samsung_SSD_980_PRO_1TB_S5GXNX0T308527F
            type: nvme
            name: boot-nvme
```

## Handlers

- `Restart smartd` – Restarts the smartmontools service when configuration changes

## Tags

- `smartd` – run all tasks in this role

## Testing

```bash
# From repo root
just test-role smartd

# Verify on target host
systemctl status smartmontools
cat /etc/smartd.conf
smartctl -a /dev/sda
```

## Changelog

- **1.0.0** (2025-12-14): Initial release

## License

MIT

## Author Information

Jochen Wersdoerfer
