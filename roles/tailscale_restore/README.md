# Tailscale Restore Role

Restores Tailscale state/configuration from a backup archive and optionally re-joins the tailnet.

## Description

Extracts a backup produced by `tailscale_backup`, restores `/var/lib/tailscale`, sysconfig, and systemd drop-ins, restarts the service, and optionally runs `tailscale up` again (auth key required unless using manual mode).

## Requirements

- Debian/Ubuntu target
- Backup archive produced by `tailscale_backup`

## Role Variables

```yaml
tailscale_restore_archive: latest            # or a specific filename/path
tailscale_restore_root: "{{ tailscale_backup_root }}"
tailscale_restore_restart_service: true
tailscale_restore_cleanup: true
tailscale_restore_force_reup: true
tailscale_manual_up: false
tailscale_auth_key: ""                       # required when manual_up=false
tailscale_backup_archive_format: gztar       # must match backup format
tailscale_backup_archive_extension: tar.gz
```

Shared paths:

```yaml
tailscale_state_dir: /var/lib/tailscale
tailscale_sysconfig_path: /etc/default/tailscaled
tailscale_systemd_dropin_dir: /etc/systemd/system/tailscaled.service.d
```

## Example Playbook

```yaml
---
- name: Restore Tailscale
  hosts: macmini
  become: true
  vars:
    sops_secrets: "{{ lookup('community.sops.sops', playbook_dir + '/../secrets/prod/tailscale.yml') | from_yaml }}"
    tailscale_restore_archive: latest
  roles:
    - role: local.ops_library.tailscale_restore
      vars:
        tailscale_auth_key: "{{ sops_secrets.tailscale_auth_key }}"
        tailscale_hostname: "macmini"
```
