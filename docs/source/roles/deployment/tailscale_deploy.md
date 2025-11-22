# tailscale_deploy

Installs and joins a host to a Tailscale tailnet using the official repository. Supports non-interactive `tailscale up` with an auth key or manual join mode.

## Features

- Adds `pkgs.tailscale.com` apt repository and installs the `tailscale` package
- Enables `tailscaled` service
- Runs `tailscale up` with configurable flags (`accept-dns`, `accept-routes`, exit node, extra args)
- Defaults to `accept-dns=false` to avoid clashing with local DNS (Unbound)

## Usage

```yaml
- hosts: macmini
  become: true
  vars:
    sops_secrets: "{{ lookup('community.sops.sops', playbook_dir + '/../secrets/prod/tailscale.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.tailscale_deploy
      vars:
        tailscale_auth_key: "{{ sops_secrets.tailscale_auth_key }}"
        tailscale_hostname: macmini
        tailscale_accept_dns: false
```

Set `tailscale_manual_up: true` when you prefer to run `tailscale up` manually (e.g., during auth key rotation).
