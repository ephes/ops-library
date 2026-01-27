# sanoid

Installs and configures `sanoid` for ZFS snapshot automation.

## Requirements

- Target host must have ZFS pools/datasets already created.

## Variables

### Required

- `sanoid_templates` (mapping): Template definitions used by datasets.
- `sanoid_datasets` (list): Dataset policies that reference templates.
  - Optional per-dataset key `sanoid_skip: true` to omit an entry from `sanoid.conf`.

### Common

- `sanoid_on_calendar` (default: `hourly`): systemd timer schedule.
- `sanoid_randomized_delay_sec` (default: `15m`): jitter.

## Example

```yaml
sanoid_templates:
  timemachine:
    autosnap: "yes"
    autoprune: "yes"
    daily: 7
  precious:
    autosnap: "yes"
    autoprune: "yes"
    hourly: 24
    daily: 30
    weekly: 8
    monthly: 12

sanoid_datasets:
  - name: fast/timemachine
    template: timemachine
  - name: tank/photos
    template: precious
```
