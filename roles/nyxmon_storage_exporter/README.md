# nyxmon_storage_exporter Role

Storage health metrics exporter for Nyxmon integration.

## Description

This role installs a Python script that collects and outputs storage health metrics as JSON. It gathers SMART data from disks (temperature, health status) and ZFS pool information (health, capacity, last scrub). The script is designed to be executed via SSH from Nyxmon for custom health checks.

## Requirements

- Debian/Ubuntu with Python 3
- Root privileges (for smartctl access)
- `smartmontools` and `nvme-cli` installed (see `smartd` role)
- ZFS installed if monitoring ZFS pools

## Role Variables

### Required

```yaml
nyxmon_storage_exporter_disks:
  - device: /dev/disk/by-id/ata-WDC_WD120EFGX-68CPHN0_WD-B00MJ7WD
    type: sat
    name: tank-hdd-1
    pool: tank
  - device: /dev/disk/by-id/nvme-Samsung_SSD_980_PRO_1TB_S5GXNX0T308527F
    type: nvme
    name: boot-nvme
    pool: none

nyxmon_storage_exporter_pools:
  - fast
  - tank
```

### Optional

```yaml
nyxmon_storage_exporter_enabled: true                              # Enable/disable
nyxmon_storage_exporter_bin_path: "/usr/local/bin/nyxmon-storage-metrics"
nyxmon_storage_exporter_mode: "0755"
```

See `defaults/main.yml` for the full list.

## Output Format

The script outputs JSON with disk temperatures, health status, pool information, and ECC memory status:

```json
{
  "disks": [
    {"name": "tank-hdd-1", "device": "/dev/...", "type": "sat", "pool": "tank", "temp_c": 40, "ok": true},
    {"name": "boot-nvme", "device": "/dev/...", "type": "nvme", "pool": "none", "temp_c": 25, "ok": true}
  ],
  "pools": {
    "tank": {"health": "ONLINE", "size": "10.9T", "alloc": "7.54M", "free": "10.9T", "cap": "0%", "last_scrub_age_days": 0.5}
  },
  "ecc": {"loaded": true, "ce": null, "ue": null},
  "ts": 1702548000
}
```

## Example Playbook

```yaml
- name: Install storage exporter
  hosts: storage_servers
  become: true
  roles:
    - role: local.ops_library.nyxmon_storage_exporter
      vars:
        nyxmon_storage_exporter_pools:
          - fast
          - tank
        nyxmon_storage_exporter_disks:
          - device: /dev/disk/by-id/nvme-Samsung_SSD_980_PRO_1TB_S5GXNX0T308527F
            type: nvme
            name: boot-nvme
            pool: none
          - device: /dev/disk/by-id/ata-WDC_WD120EFGX-68CPHN0_WD-B00MJ7WD
            type: sat
            name: tank-hdd-1
            pool: tank
```

## Tags

- `nyxmon_storage_exporter` – run all tasks in this role

## Testing

```bash
# From repo root
just test-role nyxmon_storage_exporter

# Verify on target host
/usr/local/bin/nyxmon-storage-metrics | jq .
```

## Changelog

- **1.0.0** (2025-12-14): Initial release

## License

MIT

## Author Information

Jochen Wersdoerfer
