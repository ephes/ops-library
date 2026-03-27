# Headless Mode

Persist a host as a non-graphical server by setting its default systemd target
and disabling the configured display-manager stack.

## Overview

This role is intended for machines that should behave like headless servers even
if desktop packages are installed. It can:

- set the default boot target to `multi-user.target` or another non-graphical target
- disable and stop a display manager such as `gdm3`
- disable and stop extra graphical helper services such as `gnome-remote-desktop.service`

The role does not reboot the host.

## Role Variables

See `defaults/main.yml` for the full variable list.

- `headless_mode_default_target`: systemd target to set as the default boot target
- `headless_mode_display_manager_service`: optional display-manager service alias/unit to disable
- `headless_mode_disable_services`: additional service units to disable
- `headless_mode_apply_now`: when `true`, stop the configured services immediately

## Example Playbook

```yaml
- name: Keep macmini headless
  hosts: macmini
  become: true
  roles:
    - role: local.ops_library.headless_mode
      vars:
        headless_mode_default_target: "multi-user.target"
        headless_mode_display_manager_service: "gdm3"
        headless_mode_disable_services:
          - "gnome-remote-desktop.service"
        headless_mode_apply_now: true
```

## Notes

- `headless_mode_display_manager_service` accepts service aliases like `gdm3`.
- `headless_mode_apply_now: true` stops the services during the current run and
  is suitable for fixing live memory pressure without rebooting.
- If you only want to persist the boot target for later, set
  `headless_mode_apply_now: false`.
