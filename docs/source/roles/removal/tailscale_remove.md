# tailscale_remove

Removes Tailscale packages and repository, optionally logging out and purging state.

## What it does

- Stops/disables `tailscaled`
- Runs `tailscale logout` unless skipped
- Purges `tailscale` package and apt repo/key
- Optionally deletes `/var/lib/tailscale`

## Key variables

```yaml
tailscale_confirm_removal: false   # must be true to proceed
tailscale_skip_logout: false
tailscale_purge_state: false       # delete /var/lib/tailscale
```

## Example

```yaml
- hosts: macmini
  become: true
  roles:
    - role: local.ops_library.tailscale_remove
      vars:
        tailscale_confirm_removal: true
        tailscale_purge_state: true
```
