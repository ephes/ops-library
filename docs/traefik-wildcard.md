# Traefik Wildcard Certs (file-provider) for home.xn--wersdrfer-47a.de

This documents how Traefik is configured to use the wildcard Certbot DNS-01 certificate via the file-provider, and how to avoid reintroducing per-host ACME certs.

## Router TLS behavior
- Service templates emit `tls: {}` when no cert resolver is set, ensuring routers stay on TLS and use the file-provider wildcard cert.
- If you explicitly set `*_traefik_cert_resolver`, the templates will render `certResolver: <name>` instead.

## Certificates
- Wildcard cert path: `/etc/letsencrypt/live/home.xn--wersdrfer-47a.de/{fullchain.pem, privkey.pem}`.
- File-provider config: `/etc/traefik/dynamic/certificates.yml` points to the wildcard cert/key.

## Backup/Restore
- Traefik backup/restore now skips `acme.json` by default:
  - `traefik_backup_include_acme: false`
  - `traefik_restore_include_acme: false`
- Certbot DNS backup/restore remains the source of truth for the wildcard (`/etc/letsencrypt`).
- If you must restore per-host ACME, set the include flags to true and re-enable `certResolver` in the service templates.

## Ordering / Runbook hints
- On fresh installs/restores: restore/issue the wildcard via Certbot before (re)starting Traefik.
- After certs and dynamic configs are present, restart Traefik once to load the wildcard cert.
- If you ever see per-host certs being served again, check `acme.json` for stale entries and scrub them (or set include flags false and redeploy).
