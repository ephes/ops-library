# systemd_unit_masks

Mask systemd units that cannot work on a host, and clear any lingering `failed`
state so `systemctl --failed` keeps reporting only real problems.

## Why mask rather than disable

`enabled: false` stops a unit being pulled in at boot, but it can still be
started manually or dragged in by another unit's dependency. Masking symlinks
the unit to `/dev/null`, so it cannot start at all.

Reach for this only when a unit can never succeed on the host — a driver init
script with no matching hardware, a service for an absent device. If you just
want a working service switched off for now, disable it instead; masking also
blocks deliberate manual starts, which is surprising later.

## Why the failed-state reset matters

Masking a unit that has **already failed** does not clear its state. Without
`systemctl reset-failed` the unit stays in `systemctl --failed` forever, and a
permanently non-empty failed list hides genuinely new failures. This role
detects that case (`systemctl is-failed`) and resets only those units, so runs
stay idempotent rather than reporting `changed` every time.

## Variables

| Variable | Default | Description |
|---|---|---|
| `systemd_unit_masks_units` | `[]` | Units to mask. Each entry needs `unit` (including the type suffix); `reason` is optional documentation shown in task output. |
| `systemd_unit_masks_unmask` | `[]` | Units to explicitly unmask, so removing a mask is reversible through the role. |
| `systemd_unit_masks_stop_now` | `true` | Stop a unit before masking it. Masking a running unit otherwise leaves it running until reboot. |
| `systemd_unit_masks_reset_failed` | `true` | Clear `failed` state for masked units. |

Unit names must include the suffix (`openipmi.service`, not `openipmi`). A bare
name resolves to `<name>.service`, which makes it easy to mask something other
than intended, so the role rejects it.

A unit listed in both `systemd_unit_masks_units` and `systemd_unit_masks_unmask`
is rejected rather than resolved by ordering.

## Example

```yaml
- hosts: macmini
  become: true
  roles:
    - role: local.ops_library.systemd_unit_masks
      vars:
        systemd_unit_masks_units:
          - unit: openipmi.service
            reason: "Mac mini has no BMC; the LSB init script fails on every boot."
```

To undo it, move the unit across:

```yaml
        systemd_unit_masks_units: []
        systemd_unit_masks_unmask:
          - openipmi.service
```

## Verify

```bash
systemctl is-enabled openipmi.service   # -> masked
systemctl --failed                      # openipmi.service no longer listed
```
