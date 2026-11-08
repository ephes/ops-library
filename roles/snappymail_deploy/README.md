# SnappyMail Deploy Role

Deploys [SnappyMail](https://snappymail.eu/) as a PHP-FPM application behind nginx with Traefik exposure, using a persistent data directory outside the web root.

## Features

- Installs a pinned SnappyMail release from the upstream tarball with required PHP extensions.
- Moves the `data/` directory to a persistent path (default `/mnt/cryptdata/snappymail`) and wires `include.php` to use it.
- Creates a dedicated PHP-FPM pool and nginx vhost bound to `127.0.0.1:{{ snappymail_listen_port }}` (no ports exposed publicly).
- Configures the admin account and managed SnappyMail domain JSON files for IMAP/SMTP against Dovecot/Postfix.
- Renders Traefik dynamic config for HTTPS exposure using the existing wildcard certificate and optional cert resolver.
- Health check that fails the run if the login page is not reachable locally.

## Requirements

- Debian/Ubuntu host with systemd.
- Traefik file provider mounted at `/etc/traefik/dynamic/` if `snappymail_traefik_enabled` is true.
- Working IMAP/SMTP endpoints (Dovecot/Postfix) reachable from the host.
- Admin password supplied via secrets; provide either `snappymail_admin_password` (preferred) or `snappymail_admin_password_hash` (PASSWORD_DEFAULT hash).

## Usage

```yaml
- hosts: macmini
  become: true
  vars:
    sops_secrets: "{{ lookup('community.sops.sops', playbook_dir + '/../secrets/prod/snappymail.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.snappymail_deploy
      vars:
        snappymail_admin_password: "{{ sops_secrets.snappymail_admin_password }}"
        snappymail_traefik_host: "webmail.home.xn--wersdrfer-47a.de"
        snappymail_imap_host: "imap.home.xn--wersdrfer-47a.de"
        snappymail_smtp_host: "smtp.home.xn--wersdrfer-47a.de"
        snappymail_data_dir: "/mnt/cryptdata/snappymail"
        snappymail_domains:
          - "xn--wersdrfer-47a.de"
        snappymail_remove_domains:
          - "macmini"
```

## Key Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `snappymail_admin_password` | `CHANGEME` | Admin password (required unless `snappymail_admin_password_hash` is provided). |
| `snappymail_traefik_host` | `webmail.home.xn--wersdrfer-47a.de` | Hostname for Traefik routing and cookie headers. |
| `snappymail_data_dir` | `/mnt/cryptdata/snappymail` | Persistent data path mounted outside the web root. |
| `snappymail_imap_host` / `snappymail_imap_port` | `imap.home.xn--wersdrfer-47a.de` / `993` | IMAP endpoint SnappyMail should use. |
| `snappymail_smtp_host` / `snappymail_smtp_port` | `smtp.home.xn--wersdrfer-47a.de` / `587` | SMTP endpoint SnappyMail should use. |
| `snappymail_domains` | `[]` | Optional list of domains to manage under `domains/` in addition to `default.json`. |
| `snappymail_remove_domains` | `[]` | Optional list of obsolete domain override basenames to delete from the persistent `domains/` directory. |
| `snappymail_version` | `3.0.0` | SnappyMail version to install (pinned; `snappymail_download_checksum` is the SHA-256 of the signed upstream archive). 3.0.0 needs PHP 8.2 or newer; the role refuses an older PHP before it unpacks the release, so the previous release keeps serving. |
| `snappymail_traefik_ip_whitelist_enabled` | `true` | Put the `snappymail-ipwhitelist` `ipAllowList` on the router, so only `snappymail_traefik_ip_whitelist` sources reach the login page and the admin panel (everyone else gets `403`). Enabled with an empty list is refused. |
| `snappymail_traefik_ip_whitelist` | Tailscale ranges | Source addresses or CIDR networks; each entry is parsed before deploying. |
| `snappymail_php_version` | auto | PHP minor version for the FPM pool; auto-detected from `php` CLI when empty. |

See `defaults/main.yml` and `snappymail_shared/defaults/main.yml` for the full variable reference. The role renders `default.json` and `<domain>.json` files so SnappyMail prefers the managed JSON definitions over any legacy `.ini` overrides in the persistent data directory. It also removes matching legacy `.ini` files for managed domains, and `snappymail_remove_domains` cleans up both obsolete `.json` and `.ini` basenames from the persistent `domains/` directory.

## Known Issues

### "Edit Identity" popup on first login

When a user logs in for the first time, SnappyMail displays an "Edit Identity" popup asking for their display name. In version 2.38.2 (before the current 3.0.0 pin), the Save button in this popup may not respond (JavaScript issue).

**Workaround:** Close the popup with the X button, then configure the identity via Settings (gear icon) → Accounts → Identities.

**Alternative:** Pre-create the identity file on the server. The file must use PascalCase keys:

```bash
# Create identity for user 'alice' on domain 'example.com'
cat > /mnt/cryptdata/snappymail/_data_/_default_/storage/example.com/alice/identities << 'EOF'
[{"Id":"","Email":"alice@example.com","Name":"Alice Smith","ReplyTo":"","Bcc":"","Signature":"","SignatureInsertBefore":false}]
EOF
chown snappymail:snappymail /mnt/cryptdata/snappymail/_data_/_default_/storage/example.com/alice/identities
chmod 600 /mnt/cryptdata/snappymail/_data_/_default_/storage/example.com/alice/identities
```

The identity file is stored in the data directory and survives redeploys and backup/restore cycles.

## Release selection and HTTPS behind Traefik

The nginx site serves below `/snappymail/` only the selected release's
`static/` and `themes/` and answers everything else there with `403`: the
archive unpacks each release under `snappymail/v/<version>/` and older trees
stay on disk, so without this an old release's `include.php` (and its known
vulnerabilities) would still run. The PHP entry point stays the root
`index.php` of the selected release.

SnappyMail 3.0.0 decides `force_https` from `HTTPS` alone and no longer trusts
`X-Forwarded-Proto`. The nginx site listens on loopback only and is reached
through Traefik's TLS router, so it passes `fastcgi_param HTTPS on`; without
it every request redirects to itself.

Both templates are byte-identical to ops-deploy's `services.snappymail`
templates, so an Ansible run and a pyinfra run write the same files.

## HSTS preload policy

`snappymail_traefik_sts_preload` defaults to false. Set it explicitly to true
to retain an existing preload policy; this adds `stsPreload: true` to the route
without changing certificate, authentication or IP allowlist settings.
