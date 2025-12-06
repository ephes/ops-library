# mail_backend_deploy

Deploy a full mail backend with Postfix, Dovecot, and PostgreSQL integration.

## Overview

This role deploys the complete mail backend on macmini:

- **Postfix** for mail transfer and local delivery
- **Dovecot** for IMAP access and authentication
- **OpenDKIM** for DKIM signing
- **PostgreSQL** for virtual users, domains, and aliases

## Architecture

```
                     EDGE                              MACMINI (this role)
                    Port 25                            Port 25 (edge only)
                                                       Port 587/465 (clients)
                                                       Port 993 (IMAP)
                                                       Port 4190 (Sieve)

[Edge Relay] ────────────────────────► [Postfix] ─────► [Dovecot LMTP]
                                          │                   │
                                          │                   ▼
[Clients] ◄───────────────────────────────┴──────► [IMAP/Sieve]
            submission (587/465)                              │
                                                              ▼
                                                       [Maildir Storage]
                                                       /mnt/cryptdata/vmail/
```

## Requirements

- Debian/Ubuntu target system
- PostgreSQL server running
- Redis server running (for rspamd, optional)
- Let's Encrypt certificates via DNS-01 challenge
- Network access from edge relay

## ⚠️ Network Prerequisites (IMPORTANT)

If the backend is behind NAT (e.g., home network), you **must** configure port forwarding on your router **before** mail will flow:

| External Port | Forward To | Purpose |
|---------------|------------|---------|
| **25** | macmini:25 | Inbound mail from edge relay |
| **587** | macmini:587 | Client submission (STARTTLS) |
| **465** | macmini:465 | Client submission (implicit TLS) |
| **993** | macmini:993 | IMAP access |
| **4190** | macmini:4190 | ManageSieve (optional) |

**Without port 25 forwarding, mail from the edge relay cannot reach the backend!**

The edge relay connects to the backend via the public hostname (e.g., `smtp.home.xn--wersdrfer-47a.de`) which resolves to your home IP via DDNS. If port 25 isn't forwarded, you'll see errors like:
```
connect to smtp.home.xn--wersdrfer-47a.de[...]:25: No route to host
status=deferred
```

## Required Variables

```yaml
# Domains to host (use punycode for IDN)
mail_backend_domains:
  - "xn--wersdrfer-47a.de"
  - "wersdoerfer.de"

# PostgreSQL password for mail user
mail_backend_postgres_password: "CHANGEME"  # Set via SOPS

# Edge relay for outbound mail
mail_backend_relay_host: "mail.wersdoerfer.de"
mail_backend_relay_password: "CHANGEME"  # Set via SOPS
```

## Optional Variables

### Server Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `mail_backend_hostname` | `macmini.home.wersdoerfer.de` | Internal hostname |
| `mail_backend_mydomain` | `wersdoerfer.de` | Primary mail domain |
| `mail_backend_imap_hostname` | `imap.home.wersdoerfer.de` | IMAP hostname |
| `mail_backend_smtp_hostname` | `smtp.home.wersdoerfer.de` | SMTP hostname |

### Storage

| Variable | Default | Description |
|----------|---------|-------------|
| `mail_backend_vmail_path` | `/mnt/cryptdata/vmail` | Maildir base path |
| `mail_backend_vmail_uid` | `5000` | vmail user UID |
| `mail_backend_vmail_gid` | `5000` | vmail group GID |

### PostgreSQL

| Variable | Default | Description |
|----------|---------|-------------|
| `mail_backend_postgres_host` | `localhost` | Database host |
| `mail_backend_postgres_database` | `mail` | Database name |
| `mail_backend_postgres_user` | `mail` | Database user |

### DKIM

| Variable | Default | Description |
|----------|---------|-------------|
| `mail_backend_dkim_enabled` | `true` | Enable DKIM signing |
| `mail_backend_dkim_selector` | `mail` | DKIM selector |
| `mail_backend_dkim_key_bits` | `2048` | Key size |

### Sieve

| Variable | Default | Description |
|----------|---------|-------------|
| `mail_backend_sieve_enabled` | `true` | Enable Sieve filtering |

## Example Playbook

```yaml
---
- name: Deploy Mail Backend
  hosts: macmini
  become: true
  vars:
    mail_secrets: "{{ lookup('community.sops.sops', 'secrets/prod/mail.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.mail_backend_deploy
      vars:
        mail_backend_domains:
          - "xn--wersdrfer-47a.de"
          - "wersdoerfer.de"
        mail_backend_postgres_password: "{{ mail_secrets.postgres_password }}"
        mail_backend_relay_host: "mail.wersdoerfer.de"
        mail_backend_relay_password: "{{ mail_secrets.relay_password }}"
```

## Database Schema

The role creates these tables:

- `mail_domains` - Virtual domains
- `mail_users` - Virtual users (mailboxes)
- `mail_aliases` - Email aliases (including catch-all)
- `mail_domain_aliases` - Domain-to-domain aliases

And these views for Postfix/Dovecot lookups:

- `mail_users_view` - User email and maildir path
- `mail_aliases_view` - Alias mappings
- `mail_catchall_view` - Catch-all aliases
- `mail_domain_aliases_expanded` - Expanded domain aliases
- `mail_sender_login_view` - Sender/login binding

## Client Configuration

Mail clients must use the **full email address** (including domain) as the username:

| Setting | Value |
|---------|-------|
| Username | `jochen@xn--wersdrfer-47a.de` (full email, punycode for IDN) |
| Password | (from secrets) |
| IMAP Server | `imap.home.xn--wersdrfer-47a.de` |
| IMAP Port | 993 (SSL/TLS) |
| SMTP Server | `smtp.home.xn--wersdrfer-47a.de` |
| SMTP Port | 587 (STARTTLS) or 465 (SSL/TLS) |

**Notes:**
- For IDN domains like `wersdörfer.de`, use the punycode form (`xn--wersdrfer-47a.de`) in usernames. Some mail clients may send Unicode, which won't match the database.
- **Apple Mail:** Adding the account via Mail.app's account setup does not work reliably. Instead, add the account via **System Settings → Internet Accounts → Add Other Account → Mail Account** and use the punycode domain in the username.

## Managing Users

```sql
-- Add a new user (use punycode for IDN domains)
INSERT INTO mail_users (domain_id, localpart, password)
SELECT id, 'jochen', '{SHA512-CRYPT}$6$...'
FROM mail_domains WHERE name = 'xn--wersdrfer-47a.de';

-- Generate password hash
doveadm pw -s SHA512-CRYPT

-- Add an alias
INSERT INTO mail_aliases (source_domain_id, source_localpart, destination)
SELECT id, 'postmaster', 'jochen@wersdoerfer.de'
FROM mail_domains WHERE name = 'wersdoerfer.de';

-- Add catch-all
INSERT INTO mail_aliases (source_domain_id, source_localpart, destination)
SELECT id, '*', 'jochen@wersdoerfer.de'
FROM mail_domains WHERE name = 'wersdoerfer.de';
```

## Files Created

| Path | Description |
|------|-------------|
| `/etc/postfix/main.cf` | Postfix configuration |
| `/etc/postfix/master.cf` | Postfix services |
| `/etc/postfix/sql/*.cf` | PostgreSQL lookups |
| `/etc/dovecot/dovecot.conf` | Dovecot main config |
| `/etc/dovecot/dovecot-sql.conf.ext` | Dovecot SQL auth |
| `/etc/dovecot/conf.d/*.conf` | Dovecot modules |
| `/etc/opendkim.conf` | DKIM configuration |
| `/etc/opendkim/*.table` | DKIM signing tables |

## Services Managed

- `postfix` - Mail transfer agent
- `dovecot` - IMAP server
- `opendkim` - DKIM signing

## Ports

| Port | Protocol | Description |
|------|----------|-------------|
| 25 | SMTP | Inbound from edge (firewall restricted) |
| 587 | Submission | Client submission (STARTTLS) |
| 465 | SMTPS | Client submission (implicit TLS) |
| 993 | IMAPS | IMAP access |
| 4190 | ManageSieve | Sieve script management |

## DKIM Setup

After deployment, add DNS TXT records for each domain:

```
mail._domainkey.wersdoerfer.de.  TXT  "v=DKIM1; k=rsa; p=<public-key>"
```

The public key is displayed during deployment and stored at:
`/etc/opendkim/keys/<domain>/mail.txt`

## Troubleshooting

### Check service status
```bash
systemctl status postfix dovecot opendkim
```

### Test SMTP delivery
```bash
# Send test mail via LMTP
doveadm mailbox list -u user@domain
```

### Test authentication
```bash
doveadm auth login user@domain
```

### Check mail logs
```bash
tail -f /var/log/mail.log
journalctl -u postfix -f
journalctl -u dovecot -f
```

### Verify DKIM
```bash
opendkim-testkey -d wersdoerfer.de -s mail -vvv
```

## License

MIT
