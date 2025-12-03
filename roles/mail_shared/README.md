# mail_shared

Shared variables and defaults for the mail infrastructure roles.

## Overview

This role provides common configuration variables used across all mail-related roles:

- `mail_relay_deploy` - Edge Postfix relay
- `mail_backend_deploy` - Backend Postfix + Dovecot
- `mail_spam_deploy` - rspamd spam filtering
- `mail_backup` / `mail_restore` - Backup operations

## Usage

Include this role as a dependency or import its defaults in your playbook:

```yaml
- hosts: mail_servers
  roles:
    - role: local.ops_library.mail_shared
    - role: local.ops_library.mail_backend_deploy
```

Or access variables directly after including defaults:

```yaml
vars_files:
  - "{{ playbook_dir }}/../collections/ansible_collections/local/ops_library/roles/mail_shared/defaults/main.yml"
```

## Variables

### Domain Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `mail_domains` | `[]` | List of hosted domains (punycode for IDN) |
| `mail_primary_domain` | `wersdoerfer.de` | Primary domain for system mail |

### Server Hostnames

| Variable | Default | Description |
|----------|---------|-------------|
| `mail_relay_hostname` | `mail.wersdoerfer.de` | Edge relay hostname (must match PTR) |
| `mail_backend_imap_hostname` | `imap.home.wersdoerfer.de` | IMAP client endpoint |
| `mail_backend_smtp_hostname` | `smtp.home.wersdoerfer.de` | SMTP client endpoint |

### Network

| Variable | Default | Description |
|----------|---------|-------------|
| `mail_edge_ipv4` | `213.239.212.206` | Edge server IPv4 |
| `mail_edge_ipv6` | `2a01:4f8:a0:82dc::2` | Edge server IPv6 |
| `mail_backend_address` | `smtp.home.wersdoerfer.de` | Backend address for edge relay |

### Storage

| Variable | Default | Description |
|----------|---------|-------------|
| `mail_vmail_path` | `/mnt/cryptdata/vmail` | Maildir storage path |
| `mail_vmail_uid` | `5000` | vmail user UID |
| `mail_vmail_gid` | `5000` | vmail group GID |
| `mail_backup_path` | `/mnt/cryptdata/backups/mail` | Backup storage path |

### PostgreSQL

| Variable | Default | Description |
|----------|---------|-------------|
| `mail_postgres_database` | `mail` | Database name |
| `mail_postgres_user` | `mail` | Database user |
| `mail_postgres_host` | `localhost` | Database host |

### Security

| Variable | Default | Description |
|----------|---------|-------------|
| `mail_password_scheme` | `SHA512-CRYPT` | Password hash scheme |
| `mail_recipient_delimiter` | `+` | Plus addressing delimiter |
| `mail_tls_min_version` | `TLSv1.2` | Minimum TLS version |

## Architecture

```
INTERNET                   EDGE                          MACMINI
                          mail.wersdoerfer.de           home.wersdoerfer.de

[External Mail] ──► MX ──► [Postfix Relay] ───────────► [Postfix + Dovecot]
                           - Greylisting                  - Final delivery
                           - TLS termination              - IMAP/SMTP auth
                                                          - rspamd filtering
                                                          - PostgreSQL

[Mail Clients] ◄──────────────────────────────────────► [IMAP/SMTP]
```

## License

MIT
