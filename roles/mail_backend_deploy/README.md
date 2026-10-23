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

### Port 25 Local-delivery Clients

| Variable | Default | Description |
|----------|---------|-------------|
| `mail_backend_mynetworks` | localhost + edge IPs | Full trust: relay to any domain (through `mail_backend_relay_host`) |
| `mail_backend_local_delivery_clients` | `[]` | Single hosts (`/32`, `/128`) that may deliver on port 25 to hosted domains only |

Port 25 relays for `mail_backend_mynetworks` and rejects every other client
(`smtp/inet` `smtpd_relay_restrictions = permit_mynetworks, reject`). An address
in `mynetworks` can send to any outside domain through the edge relay, which is
more than a null client needs to deliver its own `root@` alerts to a local
mailbox. List such a host in `mail_backend_local_delivery_clients` instead:

```yaml
mail_backend_local_delivery_clients:
  - "100.64.0.10/32"
  - "2001:db8::10/128"
```

The role then

- writes `/etc/postfix/local_delivery_clients.cidr` (`<client> local_delivery_only`),
- defines the restriction class `local_delivery_only = permit_auth_destination, reject`
  in `main.cf`, and
- sets port 25 to
  `smtpd_relay_restrictions = permit_mynetworks, check_client_access cidr:/etc/postfix/local_delivery_clients.cidr, reject`.

A listed client may deliver to recipients this server is the final destination
for (`mail_backend_domains`, their aliases and alias domains). Any other
recipient gets `554 5.7.1 Relay access denied`. Submission (587/465) is
unchanged. The global restrictions still apply to these clients: sender
domains must resolve (`reject_unknown_sender_domain`), the HELO name must be
syntactically valid, and recipients must exist
(`smtpd_reject_unlisted_recipient`). Port 25 still requires TLS
(`mail_backend_smtpd_tls_security_level`), so the client must offer STARTTLS.

Entries must be one host each, in canonical form without brackets
(`2001:db8::10/128`, not `[2001:DB8::10]/128`); the role refuses anything else
before touching Postfix. With the default empty list, `main.cf` and `master.cf`
render exactly as without this feature and the map file is removed.

The role does not open the network path (firewall, tailnet ACL) to port 25,
and does not change spam filtering: if rspamd scores mail on this host
(`mail_spam_deploy`), also list the client in `mail_spam_local_addrs_extra`,
or its mail is scored as an unknown external sender (no reverse DNS, SPF for
the sender domain) and may land in Junk.

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
| `mail_backend_schema_mode` | `legacy` | SQL schema mode (`legacy` or `postfixadmin`) |
| `mail_backend_postfixadmin_domain_aliases` | `[]` | Domain alias mappings (`alias_domain` -> `target_domain`) in PostfixAdmin mode |

### DKIM

| Variable | Default | Description |
|----------|---------|-------------|
| `mail_backend_dkim_enabled` | `true` | Enable DKIM signing |
| `mail_backend_dkim_selector` | `mail` | DKIM selector |
| `mail_backend_dkim_key_bits` | `2048` | Key size |

### Sender-only Domains

| Variable | Default | Description |
|----------|---------|-------------|
| `mail_backend_sender_only_domains` | `[]` | Domains the backend signs and authorises as sender, but hosts no mailboxes for |

For an application that submits through this backend with `From:` in a domain the
backend must not host — for example a Mastodon instance on another host sending as
`notifications@fedi.example.com` — list that domain here instead of in
`mail_backend_domains`. Each entry gets:

- a DKIM keypair plus `signing.table` / `key.table` entries, so authenticated
  submission carrying `From: *@<domain>` is signed;
- a `domain` row with `active = '0'`, which is what the `alias` table's foreign key
  needs before `mail_users_sync`'s `send_as` can add the envelope-sender alias.

`active = '0'` is what keeps the domain out of `virtual_mailbox_domains`
(`virtual_domains.cf` filters on `active = '1'`), so the backend never claims to be
the final destination for it and the hosted-domain set stays exactly
`mail_backend_domains`. Existing rows are never demoted: the insert is
`ON CONFLICT DO NOTHING`, and listing a domain in both variables is rejected up
front. Because `DO NOTHING` would also let a pre-existing *active* row silently
defeat the guarantee, the role reads the row back and fails if a sender-only domain
is active — deciding whether such a domain is really hosted is an operator call, not
something a deploy should flip.

`alias_domain` rows are checked the same way. `virtual_domain_aliases.cf` resolves
recipients through `alias_domain` without consulting `domain.active`, and the role
never deletes alias-domain rows, so a domain moved out of
`mail_backend_postfixadmin_domain_aliases` into `mail_backend_sender_only_domains`
would keep accepting mail. Both the configured mappings and the live rows are
rejected; clearing a stale row is a manual `DELETE`.

Entries must be lowercase. `alias.domain` is written lowercased and its foreign key
onto `domain.domain` is case sensitive, so a mixed-case entry would pass every
case-insensitive existence check and then fail when `mail_users_sync` inserts the
send-as alias. The role rejects mixed case up front rather than letting that happen.

Sender-only domains are deliberately **not** added to `trusted.hosts`. That file is
OpenDKIM's `InternalHosts` list and matches the connecting client, not the sender
domain; signing for these domains happens because the submission session is SMTP
authenticated, which OpenDKIM already treats as origination.

Requires `mail_backend_schema_mode: postfixadmin`.

Publishing DNS is still manual — see [DKIM Setup](#dkim-setup). Until the
`<selector>._domainkey.<domain>` TXT record is live, mail leaves with a signature
receivers cannot verify, which is worse than no signature at all. Publish before
pointing the application at the backend.

### Sieve

| Variable | Default | Description |
|----------|---------|-------------|
| `mail_backend_sieve_enabled` | `true` | Enable Sieve filtering |
| `mail_backend_spam_to_junk_enabled` | `false` | Install a global `sieve_before` script that files spam into Junk |
| `mail_backend_spam_junk_mailbox` | `Junk` | Mailbox the spam-to-Junk script files into (created if missing) |
| `mail_backend_sieve_before_dir` | `/etc/dovecot/sieve/before.d` | Directory for global `sieve_before` scripts |

The spam-to-Junk script matches `X-Spam-Status: Yes, ...` (rspamd
`milter_headers` routine `x-spam-status`) or `X-Spam: Yes` (rspamd's
`add_header` action). It only does anything once a spam milter adds those
headers, see [Spam filtering](#spam-filtering). It runs before the user's own
script, so user rules cannot rescue mail it has filed.

### Spam filtering

| Variable | Default | Description |
|----------|---------|-------------|
| `mail_backend_extra_milters` | `[]` | Milters appended after OpenDKIM, e.g. `["unix:rspamd/milter.sock"]` |

`main.cf` is fully templated by this role. A milter that another role adds by
editing `main.cf` (such as `mail_spam_deploy`, which appends rspamd) is
**removed again by the next backend deploy** unless it is also listed in
`mail_backend_extra_milters`. Postfix keeps accepting mail when a listed
milter is not running (`milter_default_action = accept`), so listing rspamd
before it is installed is harmless.

```yaml
mail_backend_extra_milters:
  - "unix:rspamd/milter.sock"
mail_backend_spam_to_junk_enabled: true
```

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
| `/etc/postfix/local_delivery_clients.cidr` | Port-25 local-delivery clients (only with `mail_backend_local_delivery_clients`) |
| `/etc/dovecot/dovecot.conf` | Dovecot main config |
| `/etc/dovecot/dovecot-sql.conf.ext` | Dovecot SQL auth |
| `/etc/dovecot/conf.d/*.conf` | Dovecot modules |
| `/etc/dovecot/sieve/before.d/10-spam-to-junk.sieve` | Spam-to-Junk global script (only with `mail_backend_spam_to_junk_enabled`) |
| `/etc/opendkim.conf` | DKIM configuration |
| `/etc/opendkim/*.table` | DKIM signing tables |

## Services Managed

- `postfix` - Mail transfer agent
- `dovecot` - IMAP server
- `opendkim` - DKIM signing

## Ports

| Port | Protocol | Description |
|------|----------|-------------|
| 25 | SMTP | Inbound from edge (firewall restricted); optional local-delivery-only clients |
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

This applies to `mail_backend_sender_only_domains` as well: those get keys and
signing-table entries exactly like hosted domains do.

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
