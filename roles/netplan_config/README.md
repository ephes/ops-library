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
    networkmanager:
      passthrough:
        ipv4.dhcp-hostname: "server1"
    nameservers:
      addresses:
        - 192.168.178.1
        - 1.1.1.1

netplan_config_apply: true
netplan_config_reconfigure_interfaces: false
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
            nameservers:
              addresses:
                - 192.168.178.1
                - 1.1.1.1
```

## Notes
- Debian/Ubuntu only.
- Applying netplan can briefly interrupt SSH sessions.
- Set `netplan_config_reconfigure_interfaces: true` for `networkd` hosts that need a follow-up
  `networkctl reconfigure <iface>` pass after `netplan apply`, for example to recover links left in
  a failed state by an earlier bad route configuration.
- Do not combine `dhcp4: true` with a manual IPv4 default route in `routes`.
  Netplan can merge DHCP lease gateway state with the rendered config and reject the duplicate route.
  If you need a custom default route, use static addressing or an explicit routing-policy design instead.
- Interface entries may include raw `dhcp4_overrides`, `dhcp6_overrides`, and
  `networkmanager` mappings when backend-specific settings are required.
