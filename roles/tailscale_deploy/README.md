# Tailscale Deploy Role

Deploys and joins a host to a Tailscale tailnet using the official package repository.

## Description

This role installs the Tailscale repository, packages, and systemd service, then joins the tailnet using either an auth key (non-interactive) or a manual `tailscale up` workflow. It is intended for Debian/Ubuntu targets (macmini) and defaults to disabling Tailscale DNS to avoid clashing with local Unbound.

## Requirements

- Debian/Ubuntu target with root/sudo access
- Auth key available via SOPS when `tailscale_manual_up` is `false`
- Network access to `pkgs.tailscale.com`

## Role Variables

### Required when `tailscale_manual_up=false`

```yaml
tailscale_auth_key: ""   # SOPS-provided reusable auth key
```

### Common settings

```yaml
tailscale_hostname: "{{ inventory_hostname }}"
tailscale_manual_up: false          # Set true to skip tailscale up
tailscale_accept_routes: false
tailscale_accept_dns: false         # Prevent MagicDNS from overriding Unbound
tailscale_exit_node: ""             # Optional exit node ID/IP
tailscale_advertise_exit_node: false
tailscale_args_extra: ""            # Extra flags (e.g., --advertise-tags=tag:server)
tailscale_package_version: latest   # Or pin e.g. 1.90.6
tailscale_channel: stable           # Channel in pkgs.tailscale.com
```

Repository variables default from facts:

```yaml
tailscale_repo_distro: "{{ ansible_distribution | lower }}"
tailscale_repo_release: "{{ ansible_distribution_release }}"
tailscale_repo_component: main
tailscale_repo_base: https://pkgs.tailscale.com
tailscale_repo_keyring: /usr/share/keyrings/tailscale-archive-keyring.gpg
tailscale_repo_list_file: /etc/apt/sources.list.d/tailscale.list
```

## Example Playbook

```yaml
---
- name: Deploy Tailscale on macmini
  hosts: macmini
  become: true
  vars:
    sops_secrets: "{{ lookup('community.sops.sops', playbook_dir + '/../secrets/prod/tailscale.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.tailscale_deploy
      vars:
        tailscale_auth_key: "{{ sops_secrets.tailscale_auth_key }}"
        tailscale_hostname: "macmini"
        tailscale_accept_dns: false
        tailscale_accept_routes: false
```

## Notes

- If Tailscale is the only management path, perform initial bootstrap via LAN/console or preinstall Tailscale manually, then switch to automated deploys.
- When rotating auth keys or reusing an existing node key, set `tailscale_manual_up: true`.
