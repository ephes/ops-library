# tailscale_restore

Restores Tailscale state/configuration from an archive created by `tailscale_backup` and optionally rejoins the tailnet.

## What it does

- Unpacks the selected archive (or latest) into a staging directory
- Restores `/var/lib/tailscale`, sysconfig, and systemd drop-ins
- Restarts `tailscaled`
- Optionally reruns `tailscale up` when `tailscale_manual_up=false`

## Key variables

```yaml
tailscale_restore_archive: latest
tailscale_restore_root: "{{ tailscale_backup_root }}"
tailscale_restore_force_reup: true
tailscale_manual_up: false
tailscale_auth_key: ""    # required when manual_up=false
```

## Example

```yaml
- hosts: macmini
  become: true
  vars:
    sops_secrets: "{{ lookup('community.sops.sops', playbook_dir + '/../secrets/prod/tailscale.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.tailscale_restore
      vars:
        tailscale_restore_archive: latest
        tailscale_auth_key: "{{ sops_secrets.tailscale_auth_key }}"
```
