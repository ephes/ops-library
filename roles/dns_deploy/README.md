# DNS Deploy Role

Deploy Unbound DNS with split-horizon views and ad blocking for homelab environments.

## Features

- **Split-horizon DNS**: Different responses for LAN vs Tailscale clients
- **Ad blocking**: Via customizable blocklists (hosts format)
- **Wildcard DNS**: For Traefik-backed services (`*.home.example.com`)
- **Custom DNS entries**: Service-specific overrides
- **IDN/Punycode support**: For domains with special characters
- **Automatic blocklist updates**: Via systemd timer
- **DNSSEC validation**: For secure DNS resolution

## Requirements

- Ubuntu 20.04+ or Debian 10+
- Root or sudo access
- Network connectivity for package installation

## Quick Start

```yaml
- hosts: dns_server
  become: true
  roles:
    - role: local.ops_library.dns_deploy
      vars:
        dns_local_domain: "home.example.com"
        dns_local_domain_punycode: "home.example.com"  # Same if no special chars

        # Split-DNS configuration
        dns_split_lan_network: "192.168.1.0/24"
        dns_split_tailscale_network: "100.64.0.0/10"
        dns_split_lan_ip: "192.168.1.5"
        dns_split_tailscale_ip: "100.64.0.5"

        # Service overrides (optional)
        dns_split_services:
          - { name: "router", lan_ip: "192.168.1.1", tailscale_ip: "192.168.1.1" }
          - { name: "nas", lan_ip: "192.168.1.10", tailscale_ip: "192.168.1.10" }
```

## Architecture

```
LAN Client (192.168.x.x) → Unbound (port 53) → LAN view → Returns LAN IP
Tailscale Client (100.x.x.x) → Unbound (port 53) → Tailscale view → Returns Tailscale IP

Unbound handles everything:
- Split-DNS views based on source IP
- Ad blocking via blocklists
- Wildcard DNS for *.home.example.com
- Custom host overrides
- Recursive resolution with DNSSEC
```

## Role Variables

### Core Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `dns_local_domain` | `"home.example.com"` | Local domain for services |
| `dns_local_domain_punycode` | `"home.example.com"` | IDN encoded version |
| `dns_local_ip` | `{{ ansible_default_ipv4.address }}` | IP for wildcard resolution |

### Split-DNS Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `dns_split_lan_network` | `"192.168.0.0/16"` | LAN network range |
| `dns_split_tailscale_network` | `"100.64.0.0/10"` | Tailscale network range |
| `dns_split_lan_ip` | `{{ ansible_default_ipv4.address }}` | IP returned for LAN clients |
| `dns_split_tailscale_ip` | `""` | IP returned for Tailscale clients |
| `dns_split_services` | `[]` | Service-specific IP overrides |

### Blocklist Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `dns_blocklists_enabled` | `true` | Enable ad blocking |
| `dns_blocklists` | See defaults | List of blocklist URLs |
| `dns_allowlist` | `["github.com", ...]` | Domains never to block |

## How It Works

### Split-DNS Views

Unbound uses view-based configuration to return different IPs based on client source:

1. **LAN clients** (192.168.x.x) get LAN IPs
2. **Tailscale clients** (100.x.x.x) get Tailscale IPs
3. **Service overrides** take precedence over wildcards

### Ad Blocking

1. Blocklists are downloaded and converted to Unbound format
2. Systemd timer updates blocklists daily
3. Allowlist ensures critical domains are never blocked

### Wildcard Resolution

- `*.home.example.com` → Configured IP (LAN or Tailscale based on view)
- Specific services can override with `dns_split_services`

## Testing

```bash
# From LAN client
dig @192.168.1.5 deploy.home.example.com
# Returns: 192.168.1.5

# From Tailscale client
dig @100.64.0.5 deploy.home.example.com
# Returns: 100.64.0.5

# Test ad blocking
dig @192.168.1.5 doubleclick.net
# Returns: 0.0.0.0 or NXDOMAIN

# Test DNSSEC
dig @192.168.1.5 google.com +dnssec
# Should show AD flag for authenticated data
```

## Tailscale Integration

For Tailscale clients to use this DNS:

1. Access [Tailscale Admin Console](https://login.tailscale.com)
2. Go to DNS settings
3. Enable Magic DNS
4. Add nameserver: Your Tailscale IP (e.g., `100.64.0.5`)
5. Restrict to domain: Your punycode domain (e.g., `home.xn--example-abc.de`)

## Troubleshooting

### Wrong IP returned
- Check source network matches configured ranges
- Verify `dns_split_tailscale_ip` is set correctly
- Restart Unbound: `sudo systemctl restart unbound`

### Domains not blocked
- Check blocklist download: `sudo systemctl status unbound-blocklist.service`
- Verify domain not in allowlist
- Force update: `sudo systemctl start unbound-blocklist.service`

### Service not resolving
- Check Unbound config: `sudo unbound-checkconf`
- View logs: `sudo journalctl -u unbound -f`
- Test from server: `dig @127.0.0.1 test.home.example.com`

## Files and Directories

- `/etc/unbound/unbound.conf.d/` - Unbound configuration
- `/var/lib/unbound/` - Blocklists and data
- `/usr/local/bin/update-blocklists.sh` - Blocklist update script
- `/etc/systemd/system/unbound-blocklist.*` - Update timer and service

## License

MIT

## Author

Ansible Role for DNS deployment with split-horizon and ad blocking