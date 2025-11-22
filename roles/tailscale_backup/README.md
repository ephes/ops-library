# Tailscale Backup Role

Creates a backup of Tailscale state and configuration suitable for preserving the node key across reinstalls.

## Description

Backs up `/var/lib/tailscale` plus optional sysconfig and systemd drop-ins into a timestamped directory and archive under the configured backup root. Optionally fetches the archive to the controller.

## Requirements

- Debian/Ubuntu target
- Tailscale installed on the host

## Role Variables

```yaml
tailscale_backup_root: "{{ backup_root_prefix | default('/opt/backups') }}/tailscale"
tailscale_backup_prefix: manual
tailscale_backup_archive_format: gztar    # produces .tar.gz
tailscale_backup_archive_extension: tar.gz
tailscale_backup_include_sysconfig: true
tailscale_backup_include_dropins: true
tailscale_backup_fetch_local: true
tailscale_backup_local_dir: "{{ lookup('env', 'HOME') }}/backups/tailscale"
```

Paths are inherited from `tailscale_shared`:

```yaml
tailscale_state_dir: /var/lib/tailscale
tailscale_sysconfig_path: /etc/default/tailscaled
tailscale_systemd_dropin_dir: /etc/systemd/system/tailscaled.service.d
```

## Example Playbook

```yaml
---
- name: Backup Tailscale on macmini
  hosts: macmini
  become: true
  vars:
    tailscale_backup_prefix: "pre-reinstall"
  roles:
    - role: local.ops_library.tailscale_backup
```
