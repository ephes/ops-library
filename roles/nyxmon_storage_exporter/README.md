# nyxmon_storage_exporter Role

Storage health metrics exporter for Nyxmon integration.

## Description

This role installs a Python script that collects and outputs storage health metrics as JSON. It gathers SMART data from disks (temperature, health status), ZFS pool information (health, capacity, last scrub), optional named filesystem usage, and optional ZFS dataset capacity and snapshot-retained space. The JSON output is designed to be served over HTTP and monitored using Nyxmon's `json-metrics` check type, using system Python 3 (no venv/uv).

## Requirements

### System Requirements
- Debian/Ubuntu with system Python 3 (installed via `nyxmon_storage_exporter_packages`)
- Root privileges (for smartctl and nvme access)

### Runtime Dependencies
The role installs `nyxmon_storage_exporter_packages` (defaults to `python3`). Add optional packages to that list depending on your monitoring needs:

| Package | Required For | Suggested Usage |
|---------|--------------|-----------------|
| `python3` | Always required | Default in `nyxmon_storage_exporter_packages` |
| `zfsutils-linux` | ZFS pool monitoring | Add to `nyxmon_storage_exporter_packages` |
| `smartmontools` | SATA/SAS disk health | Add to `nyxmon_storage_exporter_packages` |
| `nvme-cli` | NVMe disk health | Add to `nyxmon_storage_exporter_packages` |

**Note:** If a command is missing (e.g., `zpool` on a non-ZFS system), the script will return a JSON error for that subsystem instead of crashing. This allows partial monitoring when not all tools are installed.

## Role Variables

### Inventory Variables

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `nyxmon_storage_exporter_disks` | list | `[]` | List of disks to monitor (see structure below) |
| `nyxmon_storage_exporter_pools` | list | `[]` | List of ZFS pool names to monitor |
| `nyxmon_storage_exporter_filesystems` | list | `[]` | List of named filesystems/paths to measure with `df -B1` |
| `nyxmon_storage_exporter_zfs_datasets` | list | `[]` | List of named ZFS datasets whose usage, availability, quotas, and snapshot-retained bytes are exported |
| `nyxmon_storage_exporter_pool_capacity_thresholds` | mapping | `{}` | Optional per-pool `warning_ratio` and `critical_ratio`, plus an optional pair of `warning_free_bytes` and `critical_free_bytes`; emits evidence-aware capacity failure booleans |

**Note:** Disk and filesystem lists default to empty. An empty pool list enables
zpool auto-discovery; capacity-threshold keys may target those discovered names.

#### Disk Entry Structure

Each disk in `nyxmon_storage_exporter_disks` must have:

| Key | Type | Description |
|-----|------|-------------|
| `device` | string | Path to disk device (use `/dev/disk/by-id/` for stability) |
| `type` | string | One of `nvme`, `ata`, `scsi`, or `sat` |
| `name` | string | Human-readable name for the disk |
| `pool` | string | ZFS pool name this disk belongs to (or `none`) |

#### Filesystem Entry Structure

Each filesystem in `nyxmon_storage_exporter_filesystems` must have:

| Key | Type | Description |
|-----|------|-------------|
| `name` | string | Stable logical name for the filesystem |
| `path` | string | Absolute path to measure via `df -B1` |

#### ZFS Dataset Entry Structure

Each entry in `nyxmon_storage_exporter_zfs_datasets` must have:

| Key | Type | Description |
|-----|------|-------------|
| `name` | string | Unique stable name used in `zfs_datasets_by_name` JSONPaths |
| `dataset` | string | ZFS dataset name passed to `zfs get`; the pool root name (for example `fast`) is valid |

### Optional Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `nyxmon_storage_exporter_enabled` | `true` | Enable/disable the exporter installation |
| `nyxmon_storage_exporter_packages` | `["python3"]` | System packages to install for the exporter |
| `nyxmon_storage_exporter_bin_path` | `/usr/local/bin/nyxmon-storage-metrics` | Path to install the script |
| `nyxmon_storage_exporter_mode` | `0755` | File permissions for the script |
| `nyxmon_storage_exporter_smartctl_no_spinup` | `false` | Add `smartctl -n standby` to avoid waking sleeping disks |
| `nyxmon_storage_exporter_quiet_hours_enabled` | `false` | When true, skip configured disk/pool probes during quiet hours |
| `nyxmon_storage_exporter_quiet_hours_start` | `06:00` | Quiet hours start (local system time, `HH:MM`) |
| `nyxmon_storage_exporter_quiet_hours_end` | `22:00` | Quiet hours end (local system time, `HH:MM`) |
| `nyxmon_storage_exporter_quiet_hours_skip_pools` | `[]` | ZFS pools to skip during quiet hours |
| `nyxmon_storage_exporter_quiet_hours_skip_disk_types` | `["sat"]` | Disk types to skip during quiet hours (e.g., `sat` for HDDs) |
| `nyxmon_storage_exporter_quiet_hours_spindown_enabled` | `false` | When true, run a spindown hook during quiet hours (rate-limited) |
| `nyxmon_storage_exporter_quiet_hours_spindown_script` | `""` | Absolute path to executable spindown script used by quiet-hours hook |
| `nyxmon_storage_exporter_quiet_hours_spindown_min_interval_sec` | `300` | Minimum seconds between quiet-hours spindown hook runs |
| `nyxmon_storage_exporter_quiet_hours_spindown_state_file` | `/run/nyxmon-storage-metrics-spindown.ts` | State file storing last quiet-hours spindown hook run timestamp |
| `nyxmon_storage_exporter_pool_cache_path` | `/var/lib/nyxmon-storage-metrics/pool-cache.json` | Last-known successful pool, disk, and dataset samples used when quiet-hours probes are skipped; deleting it discards that evidence until active probes run again |
| `nyxmon_storage_exporter_quiet_hours_cache_max_age_sec` | `172800` | Maximum age (48 hours) for quiet-hours pool, disk, and dataset cache samples |

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

nyxmon_storage_exporter_filesystems:
  - name: rootfs
    path: /

nyxmon_storage_exporter_zfs_datasets:
  - name: fast_root
    dataset: fast
  - name: timemachine
    dataset: fast/timemachine

nyxmon_storage_exporter_quiet_hours_enabled: true
nyxmon_storage_exporter_quiet_hours_start: "06:00"
nyxmon_storage_exporter_quiet_hours_end: "22:00"
nyxmon_storage_exporter_quiet_hours_skip_pools:
  - tank
nyxmon_storage_exporter_quiet_hours_skip_disk_types:
  - sat
nyxmon_storage_exporter_quiet_hours_spindown_enabled: true
nyxmon_storage_exporter_quiet_hours_spindown_script: /usr/local/bin/zfs-usb-spindown.sh
nyxmon_storage_exporter_quiet_hours_spindown_min_interval_sec: 300
```

When quiet hours skip a configured pool and a previous successful sample exists,
the exporter returns the last-known pool metrics instead of removing metric
paths such as `$.pools.tank.cap_ratio`. Cached pool payloads keep `health`,
`size`, `alloc`, `free`, `cap_ratio`, and related fields, and add:

- `skipped: true`
- `reason: "quiet_hours"`
- `cached: true`
- `cache_timestamp`
- `cache_age_seconds`

`cap` preserves zpool's whole-percent string, while `cap_ratio` is calculated
from exact `alloc_bytes / size_bytes` and retains sub-percentage alert runway.
When a pool capacity policy is configured, use `capacity_known == true` as the
warning evidence guard, `capacity_warning_failed == false` as the warning
capacity rule, and `capacity_critical_failed == false` as the critical rule.
Unknown evidence sets `capacity_known` false without impersonating a capacity
failure; an observed ratio or absolute-free breach sets the matching failure
boolean.
Cached pool capacity can be as old as
`nyxmon_storage_exporter_quiet_hours_cache_max_age_sec`. Consumers that need a
tighter freshness bound must also inspect `cached` and `cache_age_seconds`, just
as for cached dataset capacity and disk temperature.

If no sufficiently fresh successful sample exists, the exporter keeps a stable
nullable pool schema: `health` and numeric capacity/scrub fields are `null`,
`health_known` and `health_failed` are false, and the quiet-hours skip metadata
remains present. Alert on `health_known` for evidence freshness and on
`health_failed` for an observed non-ONLINE state; do not compare nullable
`health` directly with `ONLINE`.

Disk health samples are cached in the same file. A disk type skipped during
quiet hours retains its last successful payload, including `ok` and temperature,
and adds the same cache metadata, so stable SMART-health alerts remain evaluable
without spinning up a sleeping disk. `health_known` distinguishes an observed or
cached result from a quiet-hours gap, while `health_failed` becomes true only for
an observed current SMART/NVMe failure (smartctl current-failure bits, an
explicit failed health line, or a nonzero NVMe critical warning). Historical
attribute, error-log, and self-test records (bits 5-7) are exposed separately as
`smartctl_historical_failure_bits` and do not create a permanent critical state.
Until the first active-hours sample exists, or once
the sample is older than the configured maximum age, `ok` is `null`,
`health_known` is false, and `health_failed` remains false. Alert on the latter
two fields so an evidence gap warns without impersonating a disk failure.
Cached temperatures can be up to
`nyxmon_storage_exporter_quiet_hours_cache_max_age_sec` old; temperature checks
must inspect `cached` and `cache_age_seconds` or run only against active samples.
Those cache metadata keys are always present: active and uncached fallback
samples use `cached: false` with null timestamp/age values, while cache-backed
samples use `cached: true` with numeric timestamp/age values.

Configured datasets on a skipped pool are not probed independently during
quiet hours. Their last successful numeric metrics are cached with the same
metadata, preventing a dataset-level `zfs get` from waking the pool while
keeping configured JSONPaths stable. Every dataset entry always includes all
numeric metric keys. Without a sufficiently fresh sample, those values are
`null`, `metrics_known` is false, and the entry contains `ok: null`,
`skipped: true`, and `reason: "quiet_hours"`. `metrics_known` means usable
evidence exists; it does not mean the evidence is current. Cached dataset bytes
can be as old as `nyxmon_storage_exporter_quiet_hours_cache_max_age_sec`, so
capacity checks must also inspect `cached` and `cache_age_seconds`, or run only
against active samples.
On a known-good sample (`metrics_known: true`), unset quota and reservation
properties are also represented as `null`; interpret nullable property values
together with `metrics_known`, not as evidence gaps by themselves.
Cache hits are accepted only when the cached device or dataset identity exactly
matches current configuration; retargeting a reused logical name fails closed
until the new target is actively probed.

## Nyxmon Threshold Configuration

### Recommended: Use `disks_by_name` for Stable JSONPaths

The output includes a `disks_by_name` object keyed by disk name, which provides stable JSONPaths that don't change when inventory order changes:

| JSONPath | Operator | Value | Severity | Description |
|----------|----------|-------|----------|-------------|
| `$.disks_by_name.boot-nvme.health_failed` | `==` | `false` | critical | no observed boot-nvme health failure |
| `$.disks_by_name.boot-nvme.health_known` | `==` | `true` | warning | boot-nvme health evidence is fresh |
| `$.disks_by_name.fast-nvme.health_failed` | `==` | `false` | critical | no observed fast-nvme health failure |
| `$.disks_by_name.fast-nvme.health_known` | `==` | `true` | warning | fast-nvme health evidence is fresh |
| `$.disks_by_name.tank-hdd-1.health_failed` | `==` | `false` | critical | no observed tank-hdd-1 SMART failure |
| `$.disks_by_name.tank-hdd-1.health_known` | `==` | `true` | warning | tank-hdd-1 health evidence is fresh |
| `$.disks_by_name.tank-hdd-2.health_failed` | `==` | `false` | critical | no observed tank-hdd-2 SMART failure |
| `$.disks_by_name.tank-hdd-2.health_known` | `==` | `true` | warning | tank-hdd-2 health evidence is fresh |
| `$.pools.fast.health_failed` | `==` | `false` | critical | no observed fast-pool failure |
| `$.pools.fast.health_known` | `==` | `true` | warning | fast-pool health evidence is fresh |
| `$.pools.fast.capacity_known` | `==` | `true` | warning | configured pool-capacity evidence is available; pair cached evidence with an age bound |
| `$.pools.fast.capacity_warning_failed` | `==` | `false` | warning | no observed warning ratio/free-byte breach |
| `$.pools.fast.capacity_critical_failed` | `==` | `false` | critical | no observed critical ratio/free-byte breach |
| `$.pools.tank.health_failed` | `==` | `false` | critical | no observed tank-pool failure |
| `$.pools.tank.health_known` | `==` | `true` | warning | tank-pool health evidence is fresh |
| `$.pools.fast.last_scrub_age_days` | `<` | `14` | warning | scrub recency |
| `$.zfs_datasets_by_name.timemachine.metrics_known` | `==` | `true` | warning | Time Machine dataset evidence is usable (pair with cache freshness) |
| `$.zfs_datasets_by_name.timemachine.cached` | `==` | `false` | warning | Time Machine capacity evidence comes from an active sample; alternatively bound `cache_age_seconds` |
| `$.zfs_datasets_by_name.timemachine.available_bytes` | `>` | `412316860416` | warning | Time Machine dataset has more than 384 GiB available |
| `$.zfs_datasets_by_name.timemachine.used_by_snapshots_bytes` | `<` | `274877906944` | warning | snapshots retain less than 256 GiB |
| `$.ecc.loaded` | `==` | `true` | warning | ECC module loaded |
| `$.ecc.counters_available` | `==` | `true` | warning | EDAC counters are available |
| `$.ecc.correctable_ok` | `==` | `true` | warning | no observed correctable ECC errors |
| `$.ecc.uncorrectable_ok` | `==` | `true` | critical | no observed uncorrectable ECC errors |

`counters_available` is true only when every discovered controller exposes both
EDAC counters. Any counters that can be read are still summed and exported, so
an observed correctable or uncorrectable error remains alertable even when a
different controller has incomplete counter coverage.

Each dataset entry exposes `used_bytes`, `available_bytes`, `referenced_bytes`,
`used_by_snapshots_bytes`, `used_by_dataset_bytes`, `used_by_children_bytes`,
`used_by_refreservation_bytes`, `quota_bytes`, `refquota_bytes`,
`reservation_bytes`, and `refreservation_bytes`. These keys remain present with
`null` values when evidence is unavailable.

During an active or paused scrub, `last_scrub_age_days` is calculated from the
running scrub's start timestamp; after completion, it is calculated from the
completed scrub timestamp reported by `zpool status`.

### Alternative: Index-Based JSONPaths

You can also use array indices (e.g., `$.disks.0.ok`), but **the order matches `nyxmon_storage_exporter_disks`** and thresholds must be updated if you reorder disks.

| JSONPath | Operator | Value | Severity | Description |
|----------|----------|-------|----------|-------------|
| `$.disks.0.ok` | `==` | `true` | critical | boot-nvme health |
| `$.disks.1.ok` | `==` | `true` | critical | fast-nvme health |
| `$.disks.2.ok` | `==` | `true` | critical | tank-hdd-1 health |
| `$.disks.3.ok` | `==` | `true` | critical | tank-hdd-2 health |

## Output Format

The script outputs JSON with disk temperatures, health status, pool information, quiet-hours status, and ECC memory status:

```json
{
  "disks": [
    {"name": "tank-hdd-1", "device": "/dev/...", "type": "sat", "pool": "tank", "temp_c": 40, "ok": true, "health_known": true, "health_failed": false},
    {"name": "boot-nvme", "device": "/dev/...", "type": "nvme", "pool": "none", "temp_c": 25, "ok": true, "health_known": true, "health_failed": false}
  ],
  "disks_by_name": {
    "tank-hdd-1": {"name": "tank-hdd-1", "device": "/dev/...", "type": "sat", "pool": "tank", "temp_c": 40, "ok": true, "health_known": true, "health_failed": false},
    "boot-nvme": {"name": "boot-nvme", "device": "/dev/...", "type": "nvme", "pool": "none", "temp_c": 25, "ok": true, "health_known": true, "health_failed": false}
  },
  "pools": {
    "tank": {
      "health": "ONLINE",
      "health_known": true,
      "health_failed": false,
      "size": "11984625352704",
      "alloc": "7906263",
      "free": "11984617446441",
      "cap": "0",
      "size_bytes": 11984625352704,
      "alloc_bytes": 7906263,
      "free_bytes": 11984617446441,
      "cap_ratio": 0.0,
      "capacity_known": true,
      "capacity_warning_failed": false,
      "capacity_critical_failed": false,
      "last_scrub_age_days": 0.5,
      "cached": false
    }
  },
  "filesystems": [
    {
      "name": "rootfs",
      "path": "/",
      "source": "/dev/mapper/ubuntu--vg-ubuntu--lv",
      "size_bytes": 105149440000,
      "used_bytes": 11787485184,
      "avail_bytes": 87974522880,
      "used_ratio": 0.12,
      "ok": true
    }
  ],
  "filesystems_by_name": {
    "rootfs": {
      "name": "rootfs",
      "path": "/",
      "source": "/dev/mapper/ubuntu--vg-ubuntu--lv",
      "size_bytes": 105149440000,
      "used_bytes": 11787485184,
      "avail_bytes": 87974522880,
      "used_ratio": 0.12,
      "ok": true
    }
  },
  "zfs_datasets_by_name": {
    "timemachine": {
      "name": "timemachine",
      "dataset": "fast/timemachine",
      "used_bytes": 7146825580544,
      "available_bytes": 213674622976,
      "referenced_bytes": 6387487248384,
      "used_by_snapshots_bytes": 754840371200,
      "refquota_bytes": 6597069766656,
      "quota_bytes": null,
      "metrics_known": true,
      "ok": true
    }
  },
  "quiet_hours": {
    "enabled": true,
    "active": true,
    "spindown": {"enabled": true, "attempted": true, "reason": "ok"}
  },
  "ecc": {
    "loaded": true,
    "counters_available": false,
    "ce": null,
    "ue": null,
    "correctable_ok": true,
    "uncorrectable_ok": true
  },
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
        nyxmon_storage_exporter_filesystems:
          - name: rootfs
            path: /
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
