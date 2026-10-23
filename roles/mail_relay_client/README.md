# mail_relay_client Role

Minimal Postfix relay configuration for system alerting.

## Description

This role configures Postfix as a lightweight mail relay client. It's intended for servers that need to send outbound mail (alerts from smartd, ZED, cron, etc.) but are not mail servers themselves. All outbound mail is relayed through a configured smarthost.

## Requirements

- Debian/Ubuntu with `systemd`
- Root privileges
- Access to a mail relay/smarthost

## Role Variables

### Required

```yaml
mail_relay_client_relayhost: "mail.example.com"  # Smarthost address
```

### Optional

```yaml
mail_relay_client_enabled: true                  # Enable/disable the role
mail_relay_client_port: 25                       # Relay port
mail_relay_client_use_tls: false                 # Enable STARTTLS

mail_relay_client_myhostname: "{{ ansible_fqdn }}"  # HELO hostname
mail_relay_client_myorigin: "{{ ansible_fqdn }}"    # Domain appended to bare senders/recipients (must be fully qualified)

mail_relay_client_packages:
  - postfix
  - bsd-mailx

# Additional postfix settings (applied via postconf)
mail_relay_client_postfix_settings:
  inet_interfaces: "loopback-only"
  mydestination: ""
  mynetworks: "127.0.0.0/8 [::1]/128"
  compatibility_level: "3.6"
```

See `defaults/main.yml` for the full list.

### Sender and recipient domain (`mail_relay_client_myorigin`)

Postfix appends `myorigin` to every address without a domain, on both sides:
smartd's `-m root` or ZED's `ZED_EMAIL_ADDR="root"` becomes
`root@<myorigin>` as sender and as recipient. The value must therefore be a
fully qualified domain that

- the smarthost accepts as sender domain (Postfix `reject_unknown_sender_domain`
  needs an A or MX record), and
- the smarthost routes `root@` for, normally through an alias to a real
  mailbox.

The default, `ansible_fqdn`, is a bare host name on hosts without a DNS domain.
Such a host sends as `root@<host>`; the smarthost answers
`450 4.1.8 <root@host>: Sender address rejected: Domain not found`, and the
mail sits in the queue until `maximal_queue_lifetime` expires. The role
refuses an unqualified `myorigin` (no dot, a leading/trailing dot, a numeric
top-level label, or a Postfix `$parameter` expression) before it changes
Postfix. Set it explicitly on such hosts:

```yaml
mail_relay_client_myorigin: "example.com"
```

The smarthost must also accept the client. When the client only mails local
mailboxes on the smarthost, prefer a local-delivery-only grant over
`mynetworks`, which would also let it relay to the internet (with
`mail_backend_deploy`: `mail_backend_local_delivery_clients`). This role does
not configure the smarthost. If the relayhost name only resolves through
something like Tailscale MagicDNS, check `postqueue -p` after a test mail:
Postfix's chrooted SMTP client resolves with DNS (not NSS) and its own copy of
`resolv.conf`, and may not find it. A literal IP avoids that.

## Example Playbook

```yaml
- name: Configure mail relay
  hosts: all_servers
  become: true
  roles:
    - role: local.ops_library.mail_relay_client
      vars:
        mail_relay_client_relayhost: "macmini.tailde2ec.ts.net"
        mail_relay_client_port: 25
```

## Handlers

- `Restart postfix` – Restarts postfix when configuration changes

## Tags

- `mail_relay_client` – run all tasks in this role

## Testing

```bash
# From repo root
just test-role mail_relay_client

# Verify on target host
systemctl status postfix
postconf relayhost

# Sender/recipient domain and stuck mail
postconf myorigin
postqueue -p

# Test mail sending
echo "Test" | mail -s "Test Subject" admin@example.com
```

## Changelog

- **ops-library 2.73.0** (2026-10-23): Refuse an unqualified `mail_relay_client_myorigin`; document the sender/recipient domain requirement
- **1.0.0** (2025-12-14): Initial release

## License

MIT

## Author Information

Jochen Wersdoerfer
