# thermal_metrics_exporter Role

Collect a bounded allowlist of thermal and fan sensors as JSON for a local cached HTTP endpoint.

## Description

This role installs a Python script that reads:

- `lm-sensors` JSON (`sensors -j`) for host-side thermals
- local `ipmitool sensor list -c` for BMC/IPMI thermals and fan tach

The script is designed for a privilege-split monitoring path:

1. root runs the exporter on a timer and writes JSON to disk
2. an unprivileged HTTP service exposes that cached JSON over Tailscale
3. Graphyard ingests the bounded allowlist through `http_json_metric`

The first intended production use is Fractal chassis/component thermals, but the
role is inventory-driven rather than hard-coded to one host.

## Requirements

- Debian/Ubuntu with system Python 3
- `lm-sensors`
- `ipmitool`
- root privileges for local IPMI access

These are installed through `thermal_metrics_exporter_packages` by default.

## Role Variables

### Required inventory lists

| Variable | Default | Description |
|----------|---------|-------------|
| `thermal_metrics_exporter_lm_sensors` | `[]` | Allowlist of host-side sensors from `sensors -j` |
| `thermal_metrics_exporter_ipmi_sensors` | `[]` | Allowlist of local BMC/IPMI sensors from `ipmitool sensor list -c` |

### Optional variables

| Variable | Default | Description |
|----------|---------|-------------|
| `thermal_metrics_exporter_enabled` | `true` | Enable or disable exporter installation |
| `thermal_metrics_exporter_packages` | `["python3", "lm-sensors", "ipmitool"]` | Packages installed for the exporter |
| `thermal_metrics_exporter_bin_path` | `/usr/local/bin/thermal-metrics-exporter` | Exporter script path |
| `thermal_metrics_exporter_mode` | `0755` | Exporter script file mode |

### `thermal_metrics_exporter_lm_sensors` entry

Each entry must include:

| Key | Description |
|-----|-------------|
| `id` | Stable JSON object key (letters/numbers/underscore only) |
| `source_entity_id` | Stable upstream identity, for example `lm_sensors:k10temp:Tctl` |
| `feature_name` | Sensor feature/object name from `sensors -j` |
| `value_key` | Value field inside that feature, for example `temp1_input` |
| `chip_name_regex` or `device_path` | Either a regex that matches a chip name from `sensors -j`, or an absolute NVMe device path that resolves to the matching `nvme-pci-XXXX` sensor key |

Optional:

- `sensor_label`
- `sensor_class`
- `metric_kind`
- `unit`

### `thermal_metrics_exporter_ipmi_sensors` entry

Each entry must include:

| Key | Description |
|-----|-------------|
| `id` | Stable JSON object key (letters/numbers/underscore only) |
| `sensor_name` | Exact sensor label from `ipmitool sensor list -c` |
| `source_entity_id` | Stable upstream identity, for example `ipmi:TEMP_CPU` |

Optional:

- `sensor_label`
- `sensor_class`
- `metric_kind`

## Output shape

Example:

```json
{
  "lm_sensors": {
    "cpu_tctl": {
      "collector_kind": "lm_sensors",
      "source_entity_id": "lm_sensors:k10temp:Tctl",
      "sensor_class": "cpu",
      "sensor_label": "cpu_tctl",
      "chip_name": "k10temp-pci-00c3",
      "feature_name": "Tctl",
      "metric_kind": "temperature",
      "unit": "celsius",
      "value": 31.25
    }
  },
  "ipmi": {
    "TEMP_CPU": {
      "collector_kind": "ipmi",
      "source_entity_id": "ipmi:TEMP_CPU",
      "sensor_class": "cpu",
      "sensor_label": "TEMP_CPU",
      "sensor_name": "TEMP_CPU",
      "metric_kind": "temperature",
      "status": "ok",
      "unit": "celsius",
      "value": 26.0
    }
  },
  "ts": 1773147600
}
```

Missing or unreadable sensors stay visible in the payload with an `error` object
so operators can distinguish parser drift from a totally missing endpoint.

## Example playbook usage

```yaml
- name: Install thermal exporter
  hosts: fractal
  become: true
  roles:
    - role: local.ops_library.thermal_metrics_exporter
      vars:
        thermal_metrics_exporter_lm_sensors:
          - id: cpu_tctl
            source_entity_id: "lm_sensors:k10temp:Tctl"
            chip_name_regex: "^k10temp-"
            feature_name: "Tctl"
            value_key: "temp1_input"
            sensor_label: "cpu_tctl"
            sensor_class: "cpu"
        thermal_metrics_exporter_ipmi_sensors:
          - id: TEMP_CPU
            sensor_name: "TEMP_CPU"
            source_entity_id: "ipmi:TEMP_CPU"
            sensor_label: "TEMP_CPU"
            sensor_class: "cpu"
```

## Validation

```bash
# On target host
/usr/local/bin/thermal-metrics-exporter | jq .
```
