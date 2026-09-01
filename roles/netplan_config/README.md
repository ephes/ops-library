# netplan_config Role

Configure persistent network settings using Netplan.

## Features
- Templates a single `/etc/netplan/99-ops-library.yaml`.
- Optional cleanup of conflicting netplan files.
- Runs `netplan generate` and (optionally) `netplan apply`.
- Optional systemd route guard for recovering networkd links that retain carrier
  but lose their IPv4 default route or enter a failed setup state.

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
netplan_config_route_guard_enabled: false
netplan_config_route_guard_interfaces: []
netplan_config_route_guard_interval_sec: 60
netplan_config_route_guard_confirmation_delay_sec: 5
netplan_config_route_guard_recovery_delay_sec: 10
netplan_config_route_guard_service_name: netplan-route-guard
netplan_config_route_guard_script_path: /usr/local/sbin/netplan-route-guard
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
        netplan_config_route_guard_enabled: true
        netplan_config_route_guard_interfaces:
          - enp1s0f1
```

## Notes
- Debian/Ubuntu only.
- Applying netplan can briefly interrupt SSH sessions.
- Set `netplan_config_reconfigure_interfaces: true` for `networkd` hosts that need a follow-up
  `networkctl reconfigure <iface>` pass after `netplan apply`, for example to recover links left in
  a failed state by an earlier bad route configuration.
- `netplan_config_route_guard_enabled` installs a root-owned oneshot service and
  timer. The guard does nothing while carrier is absent or while the link has a
  default route and a non-failed networkd setup state. Otherwise it runs
  `networkctl reconfigure`, waits briefly, and fails visibly if the route or
  setup state did not recover. The minimum timer interval is 15 seconds. Every
  guarded interface must be listed explicitly and must be expected to own an
  IPv4 default route; the list defaults to empty. Increase the recovery delay
  for DHCP links that need longer to reacquire a lease and route. Managed
  `netplan generate`, `netplan apply`, and follow-up `networkctl reconfigure`
  operations take the same lock as the guard, so recovery commands never run
  concurrently with those operations. A timer tick may run between apply and a
  separate follow-up reconfigure, but the second lock acquisition waits for it
  to finish.
- The guard and Tailscale exporter inspect the main IPv4 routing table. Do not
  enable this default-route probe for policy-routing designs whose default route
  exists only in another table.
- A newly missing route is confirmed after the configurable confirmation delay
  before recovery, so normal boot and post-carrier configuration can finish.
  Failed networkd setup state is acted on immediately. The oneshot timeout is
  derived from both configured delays and the number of guarded interfaces.
- The timer waits two minutes after its initial activation before its first
  probe. A later timer restart can retain the service's existing monotonic
  schedule, so correctness during managed network changes comes from the shared
  lock rather than from assuming another two-minute grace period.
- Probe errors and missing configured interfaces make the service fail and log,
  but do not themselves trigger a reconfigure. A definitively missing route or
  failed networkd state is required before the guard changes the interface.
- `pending`, `initialized`, and `configuring` networkd states are left alone for
  a later timer tick. `failed` is a recoverable fault whenever carrier is
  present; `unmanaged` and `linger` are recoverable when the default route is
  also missing. Missing-route recovery for all three non-failed recoverable
  states honors the confirmation delay. Failed-state
  detection uses the JSON `AdministrativeState` field from systemd 255 as
  shipped by Ubuntu 24.04; Python 3 is required on the host.
- An unrecoverable fault is retried at every configured interval. Choose an
  interval that balances recovery time against repeated reconfiguration, and
  alert on failed guard service runs so a persistent upstream fault is visible.
- Setting `netplan_config_route_guard_enabled: false` stops and removes a guard
  previously installed under the configured service and script names. The role
  deliberately fails instead of deleting files at those paths when they do not
  contain its ownership marker; resolve the name collision or remove the
  unrelated files explicitly.
- Enabling the guard applies the same ownership check before writing its script
  and units, so a colliding unmanaged file is never overwritten.
- For infrastructure servers, prefer a fully static address and route or a fully
  DHCP-managed address and route. Do not combine the two.
- Do not combine `dhcp4: true` with a manual IPv4 default route in `routes`.
  Netplan can merge DHCP lease gateway state with the rendered config and reject the duplicate route.
  If you need a custom default route, use static addressing or an explicit routing-policy design instead.
- Interface entries may include raw `dhcp4_overrides`, `dhcp6_overrides`, and
  `networkmanager` mappings when backend-specific settings are required.
