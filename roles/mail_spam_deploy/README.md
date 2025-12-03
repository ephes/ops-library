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

### Via IMAP (with Dovecot plugin)

Move mail to Junk folder = spam
Move mail from Junk = ham

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
