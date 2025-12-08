# Vaultwarden Deploy Role

Deploy [Vaultwarden](https://github.com/dani-garcia/vaultwarden), a self-hosted Bitwarden-compatible password manager.

## Overview

This role installs Vaultwarden using pre-built `.deb` packages from [vaultwarden-deb](https://vaultwarden-deb.pages.dev/), configures it as a systemd service, and sets up Traefik reverse proxy integration.

## Features

- **No Docker required** - Native systemd service
- **Automatic updates** - Via standard `apt upgrade`
- **Full Bitwarden compatibility** - Works with all official clients
- **SSH key support** - Experimental SSH agent feature enabled
- **WebSocket support** - Live sync across devices
- **Security hardened** - Systemd security options enabled

## Quick Start

```yaml
- hosts: server
  roles:
    - role: local.ops_library.vaultwarden_deploy
      vars:
        vaultwarden_domain: "https://vault.example.com"
        vaultwarden_admin_token: "{{ vault_admin_token }}"
        vaultwarden_smtp_host: "localhost"
        vaultwarden_smtp_from: "vault@example.com"
```

## Requirements

- Debian 11/12/13 or Ubuntu 22.04/24.04
- Traefik reverse proxy (for HTTPS)
- Valid TLS certificate (via certbot_dns or Traefik)

## Role Variables

### Required Variables

| Variable | Description |
|----------|-------------|
| `vaultwarden_domain` | Full URL (e.g., `https://vault.example.com`) |
| `vaultwarden_admin_token` | Admin panel access token (generate with `openssl rand -base64 48`) |

### Optional Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `vaultwarden_rocket_address` | `127.0.0.1` | Bind address |
| `vaultwarden_rocket_port` | `8000` | HTTP port |
| `vaultwarden_websocket_enabled` | `true` | Enable WebSocket for live sync |
| `vaultwarden_websocket_port` | `3012` | WebSocket port |
| `vaultwarden_signups_allowed` | `false` | Allow public registration |
| `vaultwarden_invitations_allowed` | `true` | Allow user invitations |
| `vaultwarden_smtp_host` | `""` | SMTP server for emails |
| `vaultwarden_smtp_port` | `587` | SMTP port |
| `vaultwarden_smtp_security` | `starttls` | SMTP security (starttls/force_tls/off) |
| `vaultwarden_smtp_from` | `""` | From email address |
| `vaultwarden_traefik_enabled` | `true` | Deploy Traefik config |
| `vaultwarden_traefik_entrypoint` | `websecure` | Traefik entrypoint |

### SSH Key Support

SSH key storage and agent support is enabled by default via experimental feature flags:

```yaml
vaultwarden_experimental_client_feature_flags: "ssh-key-vault-item,ssh-agent"
```

This requires Bitwarden desktop client version 2024.12.0 or newer.

## File Locations

Paths are set by the `.deb` packages:

| Path | Description |
|------|-------------|
| `/usr/bin/vaultwarden` | Server binary |
| `/etc/vaultwarden.env` | Configuration file |
| `/var/lib/vaultwarden/data` | Database and attachments |
| `/var/lib/vaultwarden/web-vault` | Web interface files |
| `/var/log/vaultwarden` | Log files |

## Post-Installation

### Initial Setup

1. Access the admin panel at `https://your-domain/admin`
2. Create your first user account
3. **Disable signups** after creating accounts (already disabled by default)
4. Configure organization for family sharing
5. Set up emergency access contacts

### Client Setup

Configure Bitwarden clients to use your self-hosted server:

1. Open Bitwarden app
2. Click "Self-hosted" or settings icon
3. Enter your server URL: `https://vault.example.com`
4. Log in or create account

### Bitwarden CLI

```bash
# Install CLI
npm install -g @bitwarden/cli

# Configure server
bw config server https://vault.example.com

# Login
bw login

# Unlock and get session
export BW_SESSION=$(bw unlock --raw)

# Get a password
bw get password "GitHub"
```

## Backup

The Vaultwarden data consists of:

- **SQLite database**: `/var/lib/vaultwarden/data/db.sqlite3`
- **Attachments**: `/var/lib/vaultwarden/data/attachments/`
- **RSA keys**: `/var/lib/vaultwarden/data/rsa_key.*`
- **Sends**: `/var/lib/vaultwarden/data/sends/`

Use the `vaultwarden_backup` role for automated backups.

## Troubleshooting

### Service won't start

```bash
# Check service status
sudo systemctl status vaultwarden

# View logs
sudo journalctl -u vaultwarden -f

# Check configuration
sudo cat /etc/vaultwarden.env
```

### WebSocket not working

Ensure Traefik is routing `/notifications/hub` to the WebSocket port:

```bash
# Test WebSocket endpoint
curl -I https://vault.example.com/notifications/hub
```

### Admin panel inaccessible

Verify the admin token is set in `/etc/vaultwarden.env`:

```bash
sudo grep ADMIN_TOKEN /etc/vaultwarden.env
```

### Email not sending

Test SMTP configuration:

```bash
# Check SMTP settings
sudo grep SMTP /etc/vaultwarden.env

# Test with swaks (install: apt install swaks)
swaks --to test@example.com --server localhost --port 25
```

## Security Considerations

1. **Use strong admin token** - Generate with `openssl rand -base64 48`
2. **Disable signups** - Use invitations instead
3. **Enable 2FA** - Require for all users
4. **Regular backups** - Test restore procedures
5. **Keep updated** - Run `apt upgrade` regularly

## References

- [Vaultwarden GitHub](https://github.com/dani-garcia/vaultwarden)
- [Vaultwarden Wiki](https://github.com/dani-garcia/vaultwarden/wiki)
- [Bitwarden Help Center](https://bitwarden.com/help/)
- [vaultwarden-deb Packages](https://vaultwarden-deb.pages.dev/)
