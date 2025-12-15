# nyxmon_storage_exporter Role

Storage health metrics exporter for Nyxmon integration.

## Description

This role installs a Python script that collects and outputs storage health metrics as JSON. It gathers SMART data from disks (temperature, health status) and ZFS pool information (health, capacity, last scrub). The script is designed to be executed via SSH from Nyxmon for custom health checks.

## Requirements

### System Requirements
- Debian/Ubuntu with Python 3
- Root privileges (for smartctl and nvme access)

### Runtime Dependencies
The following packages should be installed depending on your monitoring needs:

| Package | Required For | Install Command |
|---------|--------------|-----------------|
| `python3` | Always required | `apt install python3` |
| `zfsutils-linux` | ZFS pool monitoring | `apt install zfsutils-linux` |
| `smartmontools` | SATA/SAS disk health | `apt install smartmontools` |
| `nvme-cli` | NVMe disk health | `apt install nvme-cli` |

**Note:** If a command is missing (e.g., `zpool` on a non-ZFS system), the script will return a JSON error for that subsystem instead of crashing. This allows partial monitoring when not all tools are installed.

## Role Variables

### Inventory Variables

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `nyxmon_storage_exporter_disks` | list | `[]` | List of disks to monitor (see structure below) |
| `nyxmon_storage_exporter_pools` | list | `[]` | List of ZFS pool names to monitor |

**Note:** Both lists default to empty. If empty, the exporter will still run but report no disk/pool data. Configure at least one of these to get meaningful metrics.

#### Disk Entry Structure

Each disk in `nyxmon_storage_exporter_disks` must have:

| Key | Type | Description |
|-----|------|-------------|
| `device` | string | Path to disk device (use `/dev/disk/by-id/` for stability) |
| `type` | string | One of `nvme`, `ata`, `scsi`, or `sat` |
| `name` | string | Human-readable name for the disk |
| `pool` | string | ZFS pool name this disk belongs to (or `none`) |

### Optional Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `nyxmon_storage_exporter_enabled` | `true` | Enable/disable the exporter installation |
| `nyxmon_storage_exporter_bin_path` | `/usr/local/bin/nyxmon-storage-metrics` | Path to install the script |
| `nyxmon_storage_exporter_mode` | `0755` | File permissions for the script |

See `defaults/main.yml` for the full list.

### Example Configuration

```yaml
nyxmon_storage_exporter_pools:
  - fast
  - tank

nyxmon_storage_exporter_disks:
  - device: /dev/disk/by-id/nvme-Samsung_SSD_980_PRO_1TB_S5GXNX0T308527F
    type: nvme
    name: boot-nvme
    pool: none
  - device: /dev/disk/by-id/nvme-Samsung_SSD_990_PRO_2TB_S5GXNX0T405678A
    type: nvme
    name: fast-nvme
    pool: fast
  - device: /dev/disk/by-id/ata-WDC_WD120EFGX-68CPHN0_WD-B00MJ7WD
    type: sat
    name: tank-hdd-1
    pool: tank
  - device: /dev/disk/by-id/ata-WDC_WD120EFGX-68CPHN0_WD-C00MJ8XE
    type: sat
    name: tank-hdd-2
    pool: tank
```

## Nyxmon Threshold Configuration

### Recommended: Use `disks_by_name` for Stable JSONPaths

The output includes a `disks_by_name` object keyed by disk name, which provides stable JSONPaths that don't change when inventory order changes:

| JSONPath | Operator | Value | Severity | Description |
|----------|----------|-------|----------|-------------|
| `$.disks_by_name.boot-nvme.ok` | `==` | `true` | critical | boot-nvme health |
| `$.disks_by_name.fast-nvme.ok` | `==` | `true` | critical | fast-nvme health |
| `$.disks_by_name.tank-hdd-1.ok` | `==` | `true` | critical | tank-hdd-1 health |
| `$.disks_by_name.tank-hdd-2.ok` | `==` | `true` | critical | tank-hdd-2 health |
| `$.pools.fast.health` | `==` | `ONLINE` | critical | fast pool status |
| `$.pools.tank.health` | `==` | `ONLINE` | critical | tank pool status |
| `$.pools.fast.last_scrub_age_days` | `<` | `14` | warning | scrub recency |
| `$.ecc.loaded` | `==` | `true` | warning | ECC module loaded |

### Alternative: Index-Based JSONPaths

You can also use array indices (e.g., `$.disks.0.ok`), but **the order matches `nyxmon_storage_exporter_disks`** and thresholds must be updated if you reorder disks.

| JSONPath | Operator | Value | Severity | Description |
|----------|----------|-------|----------|-------------|
| `$.disks.0.ok` | `==` | `true` | critical | boot-nvme health |
| `$.disks.1.ok` | `==` | `true` | critical | fast-nvme health |
| `$.disks.2.ok` | `==` | `true` | critical | tank-hdd-1 health |
| `$.disks.3.ok` | `==` | `true` | critical | tank-hdd-2 health |

## Output Format

The script outputs JSON with disk temperatures, health status, pool information, and ECC memory status:

```json
{
  "disks": [
    {"name": "tank-hdd-1", "device": "/dev/...", "type": "sat", "pool": "tank", "temp_c": 40, "ok": true},
    {"name": "boot-nvme", "device": "/dev/...", "type": "nvme", "pool": "none", "temp_c": 25, "ok": true}
  ],
  "disks_by_name": {
    "tank-hdd-1": {"name": "tank-hdd-1", "device": "/dev/...", "type": "sat", "pool": "tank", "temp_c": 40, "ok": true},
    "boot-nvme": {"name": "boot-nvme", "device": "/dev/...", "type": "nvme", "pool": "none", "temp_c": 25, "ok": true}
  },
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
