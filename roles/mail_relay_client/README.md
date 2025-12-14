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
mail_relay_client_myorigin: "{{ ansible_fqdn }}"    # Envelope sender domain

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

# Test mail sending
echo "Test" | mail -s "Test Subject" admin@example.com
```

## Changelog

- **1.0.0** (2025-12-14): Initial release

## License

MIT

## Author Information

Jochen Wersdoerfer
