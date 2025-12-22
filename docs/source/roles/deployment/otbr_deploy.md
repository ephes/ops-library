# OTBR Deploy

Deploys OpenThread Border Router (OTBR) from source using the upstream `ot-br-posix` scripts, then configures `/etc/default/otbr-agent` and systemd for the ZBT-2 radio.

## Features

- Clones and builds `openthread/ot-br-posix` via `script/bootstrap` + `script/setup`.
- Manages `otbr-agent` runtime options, including REST API listen address/port.
- Enables the `otbr-agent` systemd unit (optionally `otbr-web`).
- Installs a ZBT-2 udev rule to ensure `dialout` permissions.

## Key Variables

- `otbr_rcp_device` (required) - Serial device path for the ZBT-2 RCP.
- `otbr_infra_interface` - Backbone interface (defaults to primary IPv4 interface when available).
- `otbr_rest_listen_address` / `otbr_rest_listen_port` - REST API binding for Home Assistant.
- `otbr_web_enabled` - Build and run the optional OTBR web UI.
- `otbr_mdns` / `otbr_dhcp6_pd_client` - Network feature tuning.
- `otbr_remove_bind` - Remove the `bind9` package installed by `script/bootstrap` to avoid DNS conflicts.

See `roles/otbr_deploy/defaults/main.yml` for all variables.

By default the role removes `bind9` after bootstrap so Unbound (or another DNS
service) can bind to port 53 without conflicts. Set `otbr_remove_bind: false`
to keep BIND installed.

## Usage

```yaml
- hosts: otbr_hosts
  become: true
  vars:
    otbr_rcp_device: "/dev/serial/by-id/usb-Espressif_..."
    otbr_infra_interface: "eno1"
    otbr_rest_listen_address: "0.0.0.0"
  roles:
    - role: local.ops_library.otbr_deploy
```
