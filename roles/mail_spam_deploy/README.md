# mail_spam_deploy

Deploy rspamd spam filter for the mail backend.

## Overview

This role deploys rspamd on the mail backend for spam filtering:

- **Spam scoring** - Multi-factor spam detection
- **Bayes learning** - Adaptive spam filter via Redis
- **Milter integration** - Postfix integration via milter protocol
- **Web UI** - Optional web interface for statistics

## Architecture

```
[Postfix] ────► [rspamd milter] ────► [Dovecot LMTP]
                     │
                     ▼
                 [Redis]
              (Bayes storage)
```

## Requirements

- Debian/Ubuntu target system
- Postfix installed (mail_backend_deploy)
- Redis server running

## Optional Variables

### Redis

| Variable | Default | Description |
|----------|---------|-------------|
| `mail_spam_redis_enabled` | `true` | Enable Redis backend |
| `mail_spam_redis_host` | `localhost` | Redis host |
| `mail_spam_redis_port` | `6379` | Redis port |
| `mail_spam_redis_password` | (none) | Redis password if required |

### Web Interface

| Variable | Default | Description |
|----------|---------|-------------|
| `mail_spam_web_enabled` | `true` | Enable web UI |
| `mail_spam_web_bind` | `127.0.0.1` | Web UI bind address |
| `mail_spam_web_port` | `11334` | Web UI port |
| `mail_spam_web_password` | (none) | Web UI password |

### Spam Thresholds

| Variable | Default | Description |
|----------|---------|-------------|
| `mail_spam_reject_score` | `15` | Score to reject mail |
| `mail_spam_add_header_score` | `6` | Score to add spam header |
| `mail_spam_greylist_score` | `4` | Score to greylist |
| `mail_spam_rewrite_subject_score` | `8` | Score to rewrite subject |
| `mail_spam_subject_prefix` | `[SPAM]` | Subject prefix for spam |

Set any threshold to `null` (`~`) to disable that action. A `null`
`mail_spam_greylist_score` also disables the greylist module, which otherwise
forces `soft reject` on its own regardless of the action threshold. On a backend behind a
relay that has already accepted the mail (edge relay -> backend), disable
`reject` and `greylist`: a reject there makes the relay send a bounce to the
envelope sender, which for spam is forged (backscatter), and greylisting only
delays the relay's retry. Tag instead and let the mailbox server file tagged
mail into Junk (`mail_backend_spam_to_junk_enabled`).

### Headers and relays

| Variable | Default | Description |
|----------|---------|-------------|
| `mail_spam_milter_headers` | `[x-spamd-bar, x-spam-level, x-spam-status, authentication-results]` | `milter_headers` routines to add |
| `mail_spam_local_addrs_default` | rspamd's built-in list | Base `local_addrs` (RFC 1918, link-local, `fd00::/8`) |
| `mail_spam_local_addrs_extra` | `[]` | Extra networks treated as local, e.g. the relay's Tailscale `/32` |
| `mail_spam_external_relay_enabled` | `false` | Score the sender behind a trusted relay instead of the relay |

`X-Spam-Status: Yes, score=...` is added for every spam verdict. The
`add_header` action's `X-Spam: Yes` is not added when a higher action such as
`rewrite_subject` applies, so match on `X-Spam-Status` in filters.

Behind a relay, rspamd only sees the relay's address. If that address has no
reverse DNS (a Tailscale `100.x` address, for example), every message scores
`RDNS_NONE` and `HFILTER_HOSTNAME_UNKNOWN` (4.5 points), and SPF and RBL checks
look at the relay. Put the relay in `mail_spam_local_addrs_extra` and enable
`mail_spam_external_relay_enabled`. rspamd's `external_relay` module, using the
`local` strategy, then takes the first `Received` hop that is not from a local
address as the real sender.

### Private DNS resolver for blocklist lookups

| Variable | Default | Description |
|----------|---------|-------------|
| `mail_spam_resolver_enabled` | `false` | Run a private recursive unbound instance for rspamd and point rspamd at it |
| `mail_spam_resolver_install_packages` | `false` | Install `unbound`, `unbound-anchor` and `bind9-dnsutils` (see the warning below) |
| `mail_spam_resolver_listen` / `mail_spam_resolver_port` | `127.0.0.1` / `5335` | Where the private instance listens |
| `mail_spam_resolver_fallback` | `127.0.0.1:53` | rspamd's fallback server (`""` = none) |
| `mail_spam_resolver_service` | `unbound-rspamd` | systemd unit name |
| `mail_spam_resolver_config` | `/etc/unbound/rspamd-resolver.conf` | Instance config |
| `mail_spam_resolver_state_dir` | `/var/lib/unbound/rspamd` | Trust anchor and working directory |

Most lists rspamd queries refuse lookups that arrive through public resolvers:
Spamhaus ZEN/DBL, SURBL, URIBL, DNSWL, Mailspike, SenderScore and others. If the
host's resolver forwards to 8.8.8.8, 1.1.1.1 or similar, those symbols end in
`*_BLOCKED` / `*_OPENRESOLVER` and contribute nothing. With
`mail_spam_resolver_enabled`, the role runs a second unbound instance. It recurses
from the root itself, listens only on loopback, and is a separate systemd unit with its
own config. rspamd then uses it as `master-slave` primary, with the host resolver as
fallback. The host's own resolver (and any LAN DNS service on it) is not touched. The
role starts the instance and checks that it answers Spamhaus's `127.0.0.2` test point
before rspamd is reconfigured.

Paths default to locations Ubuntu's AppArmor profile for `/usr/sbin/unbound`
allows. The config is deliberately outside `/etc/unbound/unbound.conf.d/`, which the
distribution's own unbound instance includes. Installing the `unbound` package also
enables that distribution instance on port 53, which can collide with
systemd-resolved or another DNS server. That's why package installation is opt-in.

### Postfix milter

This role appends `unix:rspamd/milter.sock` to `smtpd_milters` in
`/etc/postfix/main.cf`. If `mail_backend_deploy` manages the same host, list the
socket in its `mail_backend_extra_milters` too. That role templates the whole
`main.cf`, and otherwise its next run silently removes rspamd from the milter
chain, leaving rspamd running but scanning nothing.

### Package Repository

| Variable | Default | Description |
|----------|---------|-------------|
| `mail_spam_rspamd_repo_url` | `https://rspamd.com/apt-stable/` | Rspamd APT repository URL |
| `mail_spam_rspamd_legacy_repo_url` | `http://rspamd.com/apt-stable/` | Legacy unscoped Rspamd source line to remove during migration |
| `mail_spam_rspamd_repo_key_url` | `https://rspamd.com/apt-stable/gpg.key` | Rspamd repository signing key URL |
| `mail_spam_rspamd_repo_keyring` | `/etc/apt/keyrings/rspamd.asc` | Scoped keyring used by the Rspamd APT source |
| `mail_spam_rspamd_repo_legacy_key_id` | `BF21E25E` | Legacy global apt-key ID to remove during migration |
| `mail_spam_rspamd_cleanup_legacy_key` | `true` | Remove the old global apt-key entry after installing the scoped keyring |

## Example Playbook

```yaml
---
- name: Deploy Mail Spam Filter
  hosts: macmini
  become: true
  vars:
    mail_secrets: "{{ lookup('community.sops.sops', 'secrets/prod/mail.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.mail_spam_deploy
      vars:
        mail_spam_web_password: "{{ mail_secrets.rspamd_web_password }}"
```

## Files Created

| Path | Description |
|------|-------------|
| `/etc/rspamd/local.d/redis.conf` | Redis configuration |
| `/etc/rspamd/local.d/worker-normal.inc` | Worker configuration |
| `/etc/rspamd/local.d/worker-proxy.inc` | Milter configuration |
| `/etc/rspamd/local.d/worker-controller.inc` | Web UI configuration |
| `/etc/rspamd/local.d/actions.conf` | Spam actions |
| `/etc/rspamd/local.d/milter_headers.conf` | Header settings |
| `/etc/rspamd/local.d/classifier-bayes.conf` | Bayes learning |
| `/etc/rspamd/local.d/greylist.conf` | Greylist module on/off |
| `/etc/rspamd/local.d/options.inc` | `local_addrs`, and `dns` with the private resolver |
| `/etc/unbound/rspamd-resolver.conf` | Private resolver config (with `mail_spam_resolver_enabled`) |
| `/etc/systemd/system/unbound-rspamd.service` | Private resolver unit (with `mail_spam_resolver_enabled`) |
| `/etc/rspamd/local.d/external_relay.conf` | Trusted-relay handling |

`redis.conf` is mode `0640` because it may contain the Redis password.
A rspamd that cannot authenticate to Redis keeps running: it logs `NOAUTH` and
Bayes, greylisting and other Redis-backed modules silently stop working.

## Services Managed

- `rspamd` - Spam filter daemon

## Ports

| Port | Interface | Description |
|------|-----------|-------------|
| 11333 | localhost | Worker communication |
| 11334 | localhost | Web UI (if enabled) |

## Training the Filter

### Via command line

```bash
# Learn spam
rspamc learn_spam /path/to/spam.eml

# Learn ham (not spam)
rspamc learn_ham /path/to/ham.eml

# Check statistics
rspamc stat
```

Bayes only classifies once it has learned at least 200 spam and 200 ham
messages (`rspamc stat` shows the counts). Until then, `autolearn` collects
samples from clear-cut verdicts.

### Via IMAP

Learning from moves into or out of Junk (Dovecot IMAPSieve) is **not**
configured by this role.

## Web Interface

Access at `http://localhost:11334` (SSH tunnel recommended):

```bash
ssh -L 11334:localhost:11334 macmini
```

## Troubleshooting

### Check service status
```bash
systemctl status rspamd
```

### View logs
```bash
journalctl -u rspamd -f
```

### Test spam detection
```bash
rspamc < /path/to/email.eml
```

### Check Redis connection
```bash
rspamc stat
```

## License

MIT
