# SnappyMail Deploy Role

Deploys [SnappyMail](https://snappymail.eu/) as a PHP-FPM application behind nginx with Traefik exposure, using a persistent data directory outside the web root.

## Features
- Installs a pinned SnappyMail release from the upstream tarball with required PHP extensions.
- Moves the `data/` directory to a persistent path (default `/mnt/cryptdata/snappymail`) and wires `include.php` to use it.
- Creates a dedicated PHP-FPM pool and nginx vhost bound to `127.0.0.1:{{ snappymail_listen_port }}` (no ports exposed publicly).
- Configures the admin account and default domain settings for IMAP/SMTP against Dovecot/Postfix.
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
```

## Key Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `snappymail_admin_password` | `CHANGEME` | Admin password (required unless `snappymail_admin_password_hash` is provided). |
| `snappymail_traefik_host` | `webmail.home.xn--wersdrfer-47a.de` | Hostname for Traefik routing and cookie headers. |
| `snappymail_data_dir` | `/mnt/cryptdata/snappymail` | Persistent data path mounted outside the web root. |
| `snappymail_imap_host` / `snappymail_imap_port` | `imap.home.xn--wersdrfer-47a.de` / `993` | IMAP endpoint SnappyMail should use. |
| `snappymail_smtp_host` / `snappymail_smtp_port` | `smtp.home.xn--wersdrfer-47a.de` / `587` | SMTP endpoint SnappyMail should use. |
| `snappymail_domains` | `[]` | Optional list of domains to pre-create under `domains/` (fallback stays `default.ini`). |
| `snappymail_version` | `2.38.2` | SnappyMail version to install (pinned). |
| `snappymail_php_version` | auto | PHP minor version for the FPM pool; auto-detected from `php` CLI when empty. |

See `defaults/main.yml` and `snappymail_shared/defaults/main.yml` for the full variable reference.

> Backup/restore/remove roles are not yet provided. The data directory only holds SnappyMail configuration and optional address book data; mail content stays in IMAP.
