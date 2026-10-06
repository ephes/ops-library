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
# For IDNs, include the A-label (punycode).
# U-label entries are optional forward-compatibility for future SMTPUTF8 enablement.
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
| `mail_relay_inet_protocols` | `all` | Postfix address families to use/listen on (`all`, `ipv4`, or `ipv6`) |
| `mail_relay_smtp_address_preference` | `any` | Postfix outbound address-family preference (`any`, `ipv4`, or `ipv6`); this prefers but does not hard-disable fallback |
| `mail_relay_smtputf8_enable` | `false` | Advertise SMTPUTF8 support (`false` recommended for current backend LMTP compatibility) |

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
| `mail_relay_postgrey_whitelist_clients_extra` | `[]` | Extra IPs/domains to add to `/etc/postgrey/whitelist_clients` |

### Recipient Verification

| Variable | Default | Description |
|----------|---------|-------------|
| `mail_relay_verify_recipients` | `false` | Verify port-25 recipients against the backend (`reject_unverified_recipient`) |
| `mail_relay_unverified_recipient_reject_code` | `550` | Reply code for unknown recipients (Postfix default 450 only makes senders retry) |
| `mail_relay_verify_external_transport` | `discard:verified-by-srs-reverse` | `address_verify_default_transport`: answers probes for external destinations locally |

Without verification the edge accepts any local part in `mail_relay_domains`. The
backend refuses unknown ones after the edge has accepted them, and the edge then bounces
to the envelope sender, which for spam is forged (backscatter). With verification, the edge
probes the backend once per recipient. The result is cached in `address_verify_map`:
positive results for 31 days, refreshed after 7. Unknown recipients are refused at RCPT
time. The check runs after `reject_unauth_destination` and greylisting, so only our
domains are probed, and only for clients that retried. If the backend is unreachable,
unknown recipients are deferred (4xx), never accepted and bounced.

SRS bounce addresses: probes go through recipient canonical mapping, so postsrsd
reverses a valid SRS address to the original external sender. The probe for that
external address is answered locally (`mail_relay_verify_external_transport`) instead of
calling out to the sender's MX. A forged SRS address does not reverse, stays in our
domain and is verified against the backend like any other recipient.

### postscreen and DNSBL

| Variable | Default | Description |
|----------|---------|-------------|
| `mail_relay_postscreen_enabled` | `false` | Put postscreen in front of the port-25 smtpd |
| `mail_relay_postscreen_dnsbl_sites` | ZEN ×3, DNSWL negative weights | `postscreen_dnsbl_sites` entries, with answer masks |
| `mail_relay_postscreen_dnsbl_threshold` | `3` | Score at which `postscreen_dnsbl_action` applies (ZEN alone suffices) |
| `mail_relay_postscreen_dnsbl_action` | `enforce` | Action for clients above the threshold |
| `mail_relay_postscreen_greet_action` | `enforce` | Action for clients that talk before the greeting |
| `mail_relay_postscreen_access_extra` | `[]` | CIDRs that skip postscreen tests (mynetworks always do) |

Deep protocol tests stay off: they force a reconnect and gain little on top of
greylisting. The answer masks make sure DNSBL error replies (Spamhaus
`127.255.255.x`, DNSWL `127.0.0.255` for "query via public resolver") never count
as a listing. **DNSBLs refuse public resolvers.** With the host resolving through
8.8.8.8 or similar, every lookup comes back empty and postscreen silently passes
everything. See the local recursor below.

### Local Recursive Resolver

| Variable | Default | Description |
|----------|---------|-------------|
| `mail_relay_local_recursor_enabled` | `false` | Point systemd-resolved at a local recursor (drop-in) |
| `mail_relay_local_recursor_address` | `127.0.0.1` | The recursor, e.g. a BIND that recurses for localhost |
| `mail_relay_local_recursor_dropin` | `/etc/systemd/resolved.conf.d/10-mail-relay-local-recursor.conf` | Drop-in path |

The drop-in resets the global `DNS=` list to **exactly this one server**. With a
public resolver as a second entry, resolved would fail over to it on one error
and never fail back, and DNSBL lookups would silently stop working. This is
host-wide: all DNS on the host then depends on that resolver. The role refuses to
enable it unless the resolver answers Spamhaus's `127.0.0.2` test point. Disabling it
removes the drop-in and restarts systemd-resolved.

### Discarding Tagged Spam on Submission

| Variable | Default | Description |
|----------|---------|-------------|
| `mail_relay_submission_discard_spam` | `false` | Discard submitted mail whose top-level header matches the regexp |
| `mail_relay_submission_discard_spam_regexp` | `/^X-Spam-Status:[[:space:]]*Yes,/` | Header pattern (rspamd `x-spam-status` verdict) |

For backends whose aliases forward mail to external addresses: mail the backend's
spam filter tagged (for rspamd, `X-Spam-Status: Yes, ...`) is otherwise relayed to
those addresses from this host and damages its sender reputation. A dedicated
`cleanup_submission` service on 587 and 465 discards it. `nested_header_checks` and
`mime_header_checks` are emptied, so only the top-level header counts, and a spam sample
attached to a message is not matched. DISCARD rather than REJECT: a reject would make
the backend bounce to the forged sender. The backend keeps its own copy (e.g. in Junk).
Each discard is logged by cleanup (`discard: header X-Spam-Status: ...`).

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
| `/etc/postfix/postscreen_access.cidr` | postscreen access list (with `mail_relay_postscreen_enabled`) |
| `/etc/postfix/submission_header_checks` | Submission discard rule (with `mail_relay_submission_discard_spam`) |
| `/etc/systemd/resolved.conf.d/10-mail-relay-local-recursor.conf` | Resolver drop-in (with `mail_relay_local_recursor_enabled`) |

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

1. **Recipient validation** - Edge has no database access. Without `mail_relay_verify_recipients`, unknown recipients are rejected by the backend after relay, and the edge bounces to the (often forged) sender (backscatter). Enable verification to refuse them at RCPT time instead.

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
; 2a01:4f8:a0:82dc::2 → mail.wersdoerfer.de (or set mail_relay_inet_protocols: ipv4)
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
