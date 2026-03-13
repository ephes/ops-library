# netplan_config Role

Configure persistent network settings using Netplan.

## Features
- Templates a single `/etc/netplan/99-ops-library.yaml`.
- Optional cleanup of conflicting netplan files.
- Runs `netplan generate` and (optionally) `netplan apply`.

## Variables
See `defaults/main.yml` for the full list of variables.

Example configuration:
```yaml
netplan_config_renderer: "networkd"
netplan_config_cleanup_files:
  - /etc/netplan/50-cloud-init.yaml

netplan_config_interfaces:
  - name: enp1s0f1
    dhcp4: true
    dhcp6: false
    dhcp4_overrides:
      use-routes: false
    networkmanager:
      passthrough:
        ipv4.dhcp-hostname: "server1"
    routes:
      - to: default
        via: 192.168.178.1
    nameservers:
      addresses:
        - 192.168.178.1
        - 1.1.1.1

netplan_config_apply: true
```

## Example Playbook
```yaml
- hosts: servers
  become: true
  roles:
    - role: local.ops_library.netplan_config
      vars:
        netplan_config_interfaces:
          - name: enp1s0f1
            dhcp4: true
            routes:
              - to: default
                via: 192.168.178.1
```

## Notes
- Debian/Ubuntu only.
- Applying netplan can briefly interrupt SSH sessions.
- Interface entries may include raw `dhcp4_overrides`, `dhcp6_overrides`, and
  `networkmanager` mappings when backend-specific settings are required.
