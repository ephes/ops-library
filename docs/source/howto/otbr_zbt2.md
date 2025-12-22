# OTBR with Home Assistant Connect ZBT-2

This note captures research for running a docker-less OpenThread Border Router (OTBR)
with the Home Assistant Connect ZBT-2 on Ubuntu 24.04.

## Hardware and firmware summary

- ZBT-2 uses a Silicon Labs MG24 radio plus an ESP32-S3 USB-serial bridge.
- The radio interface runs at 460800 baud.
- The device is single-protocol (Zigbee or Thread, not both).
- The bootloader is unlocked and the board has exposed pads for hardware access.

## Firmware sources

- Firmware builds live in the NabuCasa silabs-firmware-builder repo.
  - OpenThread RCP manifest: `manifests/nabucasa/zbt2_openthread_rcp.yaml`.
  - Zigbee NCP manifest: `manifests/nabucasa/zbt2_zigbee_ncp.yaml`.
- The Open Home Foundation Toolbox manifest (`https://toolbox.openhomefoundation.org/assets/manifests/zbt2.json`)
  publishes ready-to-flash GBLs for Zigbee and OpenThread RCP.

## Flashing workflows

### Option A: Open Home Foundation Toolbox (recommended)

This is the simplest way to flash firmware without Home Assistant OS.

1. Open `https://toolbox.openhomefoundation.org/home-assistant-connect-zbt-2/install/` in a Chromium browser.
2. Plug the ZBT-2 into USB and follow the prompts.
3. Select the OpenThread (RCP) firmware and flash.

The toolbox manifest indicates the device supports bootloader entry over USB via
RTS/DTR or a baudrate toggle. No physical pins are required for normal flashing.

### Option B: CLI with universal-silabs-flasher

The NabuCasa universal-silabs-flasher can flash GBL files over serial.

```
python -m pip install universal-silabs-flasher

universal-silabs-flasher \
  --device /dev/ttyUSB0 \
  --bootloader-reset rts_dtr \
  flash \
  --firmware zbt2_openthread_rcp_2.4.4.0_GitHub-7074a43e4_gsdk_4.4.4.gbl
```

If `rts_dtr` fails, retry with `--bootloader-reset baudrate` (also listed in the
toolbox manifest). Use a stable `/dev/serial/by-id/...` path when possible.

### Recovery notes

- Normal recovery uses USB bootloader entry. No hardware jumpers are required.
- The board is open and has exposed pads, but a public SWD pinout has not been
  found yet. If USB bootloader entry fails, plan to confirm SWD pad labeling
  on the physical PCB before attempting a hardware recovery.

## OTBR install/build on Ubuntu 24.04

Ubuntu 24.04 (noble) does not publish OTBR packages in the main archive
(only libopenthreads is available). The supported path is a source build from
`openthread/ot-br-posix`.

Typical flow:

```
# in ot-br-posix repo
./script/bootstrap
./script/setup
```

On Ubuntu, the defaults enable the web UI and REST API (`WEB_GUI=1`, `REST_API=1`).
The bootstrap script installs runtime dependencies including:

- dbus, iptables, ipset, bind9
- avahi-daemon (when `OTBR_MDNS=avahi`)
- libnetfilter-queue (backbone router)
- protobuf, jsoncpp
- dhcpcd + radvd (optional, for DHCPv6-PD)

If the host already runs Unbound for split DNS, remove or disable `bind9` after
bootstrap (or set `otbr_remove_bind: true` in the `otbr_deploy` role) so only
Unbound listens on port 53.

## OTBR deploy role (ops-library)

Use the `otbr_deploy` role to clone, build, and configure OTBR with systemd
using the upstream scripts. Required inputs are the RCP serial device path and
the backbone interface.

Example inventory:

```yaml
otbr_rcp_device: "/dev/serial/by-id/usb-Espressif_..."
otbr_infra_interface: "eno1"
otbr_rest_listen_address: "0.0.0.0"  # expose REST API to Home Assistant
```

Notes:

- `otbr_rest_listen_address` defaults to `127.0.0.1`. Override when Home Assistant runs on another host.
- Override `otbr_rest_listen_port` if 8081 is already in use, then use the same port in Home Assistant.
- Set `otbr_web_enabled: true` if you want the optional OTBR web UI.
- Use `otbr_mdns` and `otbr_dhcp6_pd_client` to match your network requirements.

## OTBR runtime config for ZBT-2

`otbr-agent` reads `/etc/default/otbr-agent` and expects `OTBR_AGENT_OPTS`.
The `otbr_deploy` role manages this file. For ZBT-2, use the Spinel UART URL
with 460800 baud, for example:

```
OTBR_AGENT_OPTS="-I wpan0 -B eth0 spinel+hdlc+uart:///dev/serial/by-id/usb-...?
  uart-baudrate=460800"
```

Add `--rest-listen-address` if the REST API must be reachable off-host.
The REST API defaults to `127.0.0.1:8081`.

## ZBT-2 udev rule

The role installs a udev rule for the ZBT-2 (vendor `0x303a`, product `0x4001`
and `0x831a`) to ensure the serial device is owned by the `dialout` group.
Disable with `otbr_manage_udev: false` if you need custom rules.

## Home Assistant integration requirements

- Home Assistant OTBR integration expects the OTBR REST API at
  `http://<otbr-host>:8081`.
- Ensure the REST API is enabled (`REST_API=1`) and reachable from the
  Home Assistant host (open firewall, set `--rest-listen-address` as needed).
- In Home Assistant: Settings -> Devices & services -> Add integration ->
  OpenThread Border Router, then point it at the OTBR REST URL.

## Verification

```bash
# OTBR service status
systemctl status otbr-agent --no-pager

# REST API reachability (from HA host if remote)
curl --fail http://<otbr-host>:8081/node
```

## References

- Home Assistant Connect ZBT-2 product page (hardware details and baudrate):
  `https://github.com/home-assistant/home-assistant.io/tree/current/source/connect/zbt-2`
- ZBT-2 firmware sources: `https://github.com/NabuCasa/silabs-firmware-builder`
- Toolbox flasher and manifest:
  `https://toolbox.openhomefoundation.org/home-assistant-connect-zbt-2/install/`
  `https://toolbox.openhomefoundation.org/assets/manifests/zbt2.json`
- OTBR source and scripts: `https://github.com/openthread/ot-br-posix`
- Ubuntu package search (noble): `https://packages.ubuntu.com/search?keywords=otbr`
