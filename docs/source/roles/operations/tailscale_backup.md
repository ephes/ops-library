# tailscale_backup

Creates a timestamped backup of Tailscale state and configuration to preserve the node key across reinstalls.

## What it does

- Copies `/var/lib/tailscale` plus optional `/etc/default/tailscaled` and systemd drop-ins
- Stores data under `{{ backup_root_prefix }}/tailscale/<prefix>-<timestamp>/`
- Archives the backup (tar.gz) and optionally fetches it to the controller

## Key variables

```yaml
tailscale_backup_root: "{{ backup_root_prefix | default('/opt/backups') }}/tailscale"
tailscale_backup_prefix: manual
tailscale_backup_include_sysconfig: true
tailscale_backup_include_dropins: true
tailscale_backup_fetch_local: true
tailscale_backup_local_dir: "{{ lookup('env', 'HOME') }}/backups/tailscale"
```

## Example

```yaml
- hosts: macmini
  become: true
  roles:
    - role: local.ops_library.tailscale_backup
      vars:
        tailscale_backup_prefix: pre-reinstall
```
