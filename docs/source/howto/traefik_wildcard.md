# Traefik Wildcard Certs (file-provider)

This how-to covers using the wildcard Certbot DNS-01 certificate for `home.xn--wersdrfer-47a.de` via Traefik’s file-provider, and avoiding per-host ACME certs.

## Router TLS behavior
- Service templates emit `tls: {}` when no cert resolver is set, so routers stay on TLS and use the file-provider wildcard cert.
- If you set `*_traefik_cert_resolver`, the templates will render `certResolver: <name>` instead.

## Certificates
- Wildcard path: `/etc/letsencrypt/live/home.xn--wersdrfer-47a.de/{fullchain.pem, privkey.pem}`.
- File-provider config: `/etc/traefik/dynamic/certificates.yml` points to the wildcard cert/key.
- Certbot updates the targets behind the `/etc/letsencrypt/live/` symlinks. That
  does not modify Traefik's watched dynamic configuration, so the renewal hook
  must always restart Traefik; a service reload does not re-read the external
  certificate files.

## Backup/Restore
- Traefik ACME backup/restore is optional and defaults to off:
  - `traefik_backup_include_acme: false`
  - `traefik_restore_include_acme: false`
- Certbot DNS backup/restore is the source of truth for the wildcard (`/etc/letsencrypt`).
- To restore per-host ACME, set the include flags to true and re-enable `certResolver` in the service templates.

## Ordering / Runbook hints
- On fresh installs/restores: restore/issue the wildcard via Certbot before (re)starting Traefik.
- After certs and dynamic configs are present, restart Traefik once to load the wildcard cert.
- After every Certbot renewal, restart Traefik and do not mask a failed restart.
- A restart briefly interrupts proxied connections. If it fails, inspect
  `journalctl -u certbot.service` and the Let's Encrypt log for hook errors, then
  restart Traefik manually; Certbot may only log the failure and will not retry
  the deploy hook after the certificate is current.
- Rewriting or touching the watched dynamic file may also provoke a provider
  refresh, but this deployment deliberately uses the explicit systemd restart:
  the hook records the command status and the restart guarantees the certificate
  is re-read.
- If a host starts serving a per-host cert again, check `acme.json` for stale entries and scrub them (or keep the include flags false and redeploy).
