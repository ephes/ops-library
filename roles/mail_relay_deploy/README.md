# mail_relay_deploy

Deploy Postfix as an edge mail relay server.

## Overview

This role configures a thin Postfix relay on an edge server that:

- Receives inbound mail on port 25 for configured domains
- Applies greylisting via postgrey to reduce spam
- Relays accepted mail to the backend server
- Accepts authenticated outbound mail from backend on port 587

## Architecture

```
INTERNET                    EDGE (this role)              BACKEND
                           mail.wersdoerfer.de           macmini

[External MTA] ──► Port 25 ──► [Postfix Relay] ──────► Port 25 ──► [Backend Postfix]
                               - Greylisting
                               - TLS termination
                               - No recipient validation

[Backend]      ◄── Port 587 ◄── [SMTP AUTH] ◄───────────────────── [Submission]
                               - TLS required
                               - SASL authentication
```

## Requirements

- Debian/Ubuntu target system
- Let's Encrypt certificate for relay hostname
- Network connectivity to backend server

## Required Variables

```yaml
# Domains to accept mail for
# For IDNs, include the A-label (punycode) and optionally U-label if accepting SMTPUTF8 RCPT domains.
mail_relay_domains:
  - "xn--wersdrfer-47a.de"
  - "wersdörfer.de"

# Backend server to relay inbound mail to
mail_relay_backend_host: "smtp.home.xn--wersdrfer-47a.de"

# SASL password for backend authentication on submission
mail_relay_sasl_password: "CHANGEME"  # Set via SOPS
```

## Optional Variables

### Server Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `mail_relay_hostname` | `mail.wersdoerfer.de` | Hostname (must match PTR) |
| `mail_relay_mydomain` | `wersdoerfer.de` | Mail domain |
| `mail_relay_backend_port` | `25` | Backend relay port |

### TLS

| Variable | Default | Description |
|----------|---------|-------------|
| `mail_relay_tls_enabled` | `true` | Enable TLS |
| `mail_relay_tls_cert` | Let's Encrypt path | Certificate path |
| `mail_relay_tls_key` | Let's Encrypt path | Private key path |
| `mail_relay_smtpd_tls_security_level` | `may` | Inbound TLS level |

### Greylisting

| Variable | Default | Description |
|----------|---------|-------------|
| `mail_relay_greylisting_enabled` | `true` | Enable postgrey |
| `mail_relay_greylisting_delay` | `300` | Delay in seconds |

### Rate Limiting

| Variable | Default | Description |
|----------|---------|-------------|
| `mail_relay_client_connection_rate_limit` | `10` | Connections per minute |
| `mail_relay_client_recipient_rate_limit` | `100` | Recipients per minute |

### Recipient Rewrites

| Variable | Default | Description |
|----------|---------|-------------|
| `mail_relay_recipient_rewrites` | `[]` | Optional recipient envelope rewrites (`from` -> `to`) via Postfix `recipient_canonical_maps` |

When enabled, rewrites are applied to envelope recipients only (`recipient_canonical_classes = envelope_recipient`).
Supported rewrite keys/values are `user@domain` and domain-wide `@domain` patterns.

## Example Playbook

```yaml
---
- name: Deploy Mail Relay
  hosts: edge
  become: true
  vars:
    mail_secrets: "{{ lookup('community.sops.sops', 'secrets/prod/mail.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.mail_relay_deploy
      vars:
        mail_relay_domains:
          - "xn--wersdrfer-47a.de"
          - "wersdörfer.de"
        mail_relay_recipient_rewrites:
          - from: "@wersdörfer.de"
            to: "@xn--wersdrfer-47a.de"
        mail_relay_backend_host: "smtp.home.xn--wersdrfer-47a.de"
        mail_relay_sasl_password: "{{ mail_secrets.relay_sasl_password }}"
```

## Files Created

| Path | Description |
|------|-------------|
| `/etc/postfix/main.cf` | Main Postfix configuration |
| `/etc/postfix/master.cf` | Postfix service definitions |
| `/etc/postfix/transport` | Domain → backend routing |
| `/etc/postfix/relay_domains` | Accepted domains |
| `/etc/postfix/recipient_canonical` | Optional recipient rewrite map |
| `/etc/postfix/sasl_passwd` | SASL credentials |
| `/etc/postfix/sasl/smtpd.conf` | SASL configuration |
| `/etc/default/postgrey` | Greylisting settings |
| `/etc/postgrey/whitelist_clients` | Greylisting whitelist |

## Services Managed

- `postfix` - Mail transfer agent
- `postgrey` - Greylisting policy server

## Ports

| Port | Protocol | Direction | Description |
|------|----------|-----------|-------------|
| 25 | SMTP | Inbound | Receive mail from internet |
| 587 | Submission | Inbound | Accept authenticated mail from backend |
| 465 | SMTPS | Inbound | Implicit TLS submission (alternative) |

## Security Notes

1. **No recipient validation** - Edge has no database access. Unknown recipients are rejected by backend after relay. Acceptable backscatter risk for personal mail.

2. **Greylisting** - Temporarily rejects unknown senders. Reduces spam significantly.

3. **SASL authentication** - Required for submission (port 587). Backend must authenticate to send outbound mail.

4. **TLS** - Opportunistic for port 25 (internet), mandatory for submission.

## DNS Requirements

```
; MX record pointing to edge
@       MX      10      mail.wersdoerfer.de.

; A/AAAA for edge server
mail.wersdoerfer.de.    A       213.239.212.206
mail.wersdoerfer.de.    AAAA    2a01:4f8:a0:82dc::2

; PTR record (set at hosting provider)
; 213.239.212.206 → mail.wersdoerfer.de
```

## Troubleshooting

### Check Postfix status
```bash
systemctl status postfix
postfix check
```

### View mail queue
```bash
mailq
postqueue -p
```

### Check logs
```bash
tail -f /var/log/mail.log
journalctl -u postfix -f
```

### Test SMTP
```bash
# Test port 25
telnet mail.wersdoerfer.de 25

# Test with openssl
openssl s_client -connect mail.wersdoerfer.de:587 -starttls smtp
```

### Check greylisting
```bash
systemctl status postgrey
grep postgrey /var/log/mail.log
```

## License

MIT
