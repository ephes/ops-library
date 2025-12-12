# mail_relay_client

Configures a minimal Postfix installation to relay outbound mail via a smarthost.

This is intended for servers that only need to send alert emails (SMART, ZED, etc.).

## Variables

### Required

- `mail_relay_client_relayhost`: hostname/IP of the relay.

### Optional

- `mail_relay_client_port` (default: `25`)
- `mail_relay_client_use_tls` (default: `false`)
