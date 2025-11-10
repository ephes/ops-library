# Paperless Scanner Configuration Guide

How to configure a Brother MFC-L8690CDW (or similar) to upload scans directly into the Paperless-ngx SFTP inbox provisioned by `paperless_deploy`.

## Prerequisites

- Paperless deployed via ops-library/ops-control (`just deploy-one paperless`)
- Scanner user enabled (default username `scanner`, chroot `/srv/sftp-scanner`, inbox `/srv/sftp-scanner/inbox`)
- Password stored in secrets and deployed
- SSH reachable from the printer (port 22)

## 1. Collect Connection Details

| Item | Value | Notes |
| --- | --- | --- |
| Host/IP | `your-server.taildomain.ts.net` or LAN IP | Use LAN IP if printer lacks DNS |
| Port | `22` | SFTP only |
| Username | `scanner` | Match `paperless_scanner_username` |
| Password | From secrets | Update printer whenever password rotates |
| Directory | `inbox` | **No leading slash** (Brother quirk) |

Optional: export `/etc/ssh/ssh_host_rsa_key.pub` and upload via printer UI so it trusts the host key.

## 2. Configure Printer Profile

1. Browse to `http://<printer-ip>` → **Scan** → **Scan to FTP/SFTP**.
2. Add a new profile (e.g. “Paperless”).
3. Set Protocol `SFTP`, Host/Port/User/Password per table, and Store Directory `inbox`.
4. Recommended scan settings:
   - File Type `PDF`
   - Resolution `300 dpi`
   - Color Mode `Auto`
   - 2-Sided `On` (duplex profile) or `Off` (simplex)
5. Save the profile and add it to printer shortcuts.

## 3. Recommended Profiles

| Profile | Source | Duplex | Use Case |
| --- | --- | --- | --- |
| Paperless ADF | Automatic Document Feeder | On | Multi-page documents |
| Paperless Flatbed | Flatbed | Off | Passports, thick items |
| Receipts | ADF | Off | Low-res grayscale (200 dpi) |

ADF tips: load pages face-up, enable “ADF Continuous Scan” and “Skip Blank Page”.

## 4. Test Uploads

From printer: run the Paperless shortcut and wait for “Sent Successfully”.

On server:
```bash
ssh root@your-server.taildomain.ts.net
ls -lh /mnt/cryptdata/paperless/consume/
```

Monitor Paperless:
```bash
journalctl -u paperless-scheduler -f
```

## 5. Troubleshooting

| Symptom | Checks |
| --- | --- |
| Authentication failed | `ssh scanner@host`, verify `/etc/ssh/sshd_config.d/sftp-scanner.conf` |
| “Cannot send file” | `mount | grep sftp-scanner`, confirm bind mount active |
| Files not processed | `systemctl status paperless-scheduler`, inspect `/mnt/cryptdata/paperless/consume/failed` |

## 6. Maintenance

- Rotate the scanner password via SOPS + `just deploy-one paperless`, then update the printer profile.
- Failed uploads land in `/mnt/cryptdata/paperless/consume/failed`.
- Document profile changes in `ops-control/docs/PAPERLESS.md`.
