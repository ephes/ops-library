# Tailscale Remove Role

Removes Tailscale packages and repository, with optional logout and state purge.

## Description

Stops the `tailscaled` service, logs the node out (unless skipped), purges the package and apt repo, and optionally deletes `/var/lib/tailscale`. Use `tailscale_purge_state` with care if you want to preserve the machine key for future restores.

## Requirements

- Debian/Ubuntu target
- Explicit confirmation via `tailscale_confirm_removal: true`

## Role Variables

```yaml
tailscale_confirm_removal: false    # REQUIRED to run
tailscale_skip_logout: false        # Set true to keep current login session
tailscale_purge_state: false        # Remove /var/lib/tailscale (irreversible)
tailscale_repo_base: https://pkgs.tailscale.com
tailscale_repo_distro: "{{ ansible_distribution | lower }}"
tailscale_repo_release: "{{ ansible_distribution_release }}"
tailscale_repo_component: main
tailscale_repo_keyring: /usr/share/keyrings/tailscale-archive-keyring.gpg
tailscale_repo_list_file: /etc/apt/sources.list.d/tailscale.list
```

## Example Playbook

```yaml
---
- name: Remove Tailscale from macmini
  hosts: macmini
  become: true
  roles:
    - role: local.ops_library.tailscale_remove
      vars:
        tailscale_confirm_removal: true
        tailscale_skip_logout: false
        tailscale_purge_state: true   # set to true only when you intend to drop the node key
```
