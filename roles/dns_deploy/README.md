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
- **Dynamic DNS (DDNS)**: Optional automatic updates for Gandi LiveDNS (opt-in)

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

### Forward Zones Configuration

Forward zones allow specific domains to be resolved by designated upstream DNS servers. This is useful for local domains (e.g., `fritz.box`) that need resolution by a local router or appliance.

| Variable | Default | Description |
|----------|---------|-------------|
| `dns_forward_zones` | `[]` | List of forward zone configurations |

Each forward zone entry supports:

| Key | Required | Description |
|-----|----------|-------------|
| `name` | Yes | Domain to forward (e.g., `"fritz.box"`) |
| `forward_addrs` | Yes | List of upstream DNS server IPs |
| `forward_first` | No | Try forward first, fall back to local resolution on failure (default: `false`) |

**Example - Forward fritz.box to local router:**

```yaml
dns_forward_zones:
  - name: "fritz.box"
    forward_addrs:
      - "192.168.178.1"
```

**Example - Multiple forwarders for redundancy:**

```yaml
dns_forward_zones:
  - name: "corp.example.com"
    forward_addrs:
      - "10.0.0.53"
      - "10.0.0.54"
    forward_first: true
```

### Local Resolver Management

| Variable | Default | Description |
|----------|---------|-------------|
| `dns_update_resolv_conf` | `true` | Rewrite `/etc/resolv.conf` to point at Unbound |
| `dns_resolver_nameservers` | `["127.0.0.1", "{{ dns_split_lan_ip }}"]` | Ordered list of nameservers to write into `/etc/resolv.conf` |
| `dns_resolver_search_domains` | `[]` | Optional search domains appended to `resolv.conf` |
| `dns_resolver_options` | `["edns0", "trust-ad"]` | Resolver options line |

> When `dns_update_resolv_conf` is enabled (default), the role stops `systemd-resolved` and installs a static `/etc/resolv.conf` pointing at Unbound. This prevents Ubuntu upgrades from recreating a broken stub resolver.

### DDNS Configuration (Optional)

| Variable | Default | Description |
|----------|---------|-------------|
| `dns_ddns_enabled` | `false` | Enable dynamic DNS updater |
| `dns_ddns_provider` | `"gandi"` | DNS provider (only Gandi supported) |
| `dns_ddns_domain` | `"CHANGEME"` | Base domain (e.g., `"example.com"`) |
| `dns_ddns_subdomain` | `"home"` | Subdomain to update |
| `dns_ddns_update_wildcard` | `true` | Also update `*.subdomain` |
| `dns_ddns_ttl` | `300` | DNS record TTL in seconds |
| `dns_ddns_interval` | `"5min"` | Update check interval |
| `dns_ddns_api_token` | `"CHANGEME"` | Gandi LiveDNS API token |
| `dns_ddns_ipv4_enabled` | `true` | Update IPv4 (A records) |
| `dns_ddns_ipv6_enabled` | `true` | Update IPv6 (AAAA records) |
| `dns_ddns_log_max_size_mb` | `10` | Log rotation size in MB |

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

### Dynamic DNS (Optional)

When enabled (`dns_ddns_enabled: true`):

1. Detects current public IPv4 and IPv6 addresses
2. Updates Gandi LiveDNS via API when IP changes
3. Updates both base domain and wildcard (e.g., `home.example.com` and `*.home.example.com`)
4. Runs automatically via systemd timer (default: every 5 minutes)
5. Logs all updates to `/var/log/ddns/ddns-update.log`
6. Runs as dedicated `ddns` service account

**Example configuration:**

```yaml
- role: local.ops_library.dns_deploy
  vars:
    # ... other DNS vars ...

    # Enable DDNS
    dns_ddns_enabled: true
    dns_ddns_domain: "example.com"
    dns_ddns_subdomain: "home"
    dns_ddns_api_token: "{{ vault_gandi_api_token }}"  # From vault/secrets
```

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

# Test DDNS (when enabled)
sudo systemctl status ddns-update.timer
# Should be active and show next trigger time

sudo journalctl -u ddns-update.service -n 50
# View DDNS update logs

# Check DDNS log file
sudo tail -f /var/log/ddns/ddns-update.log
# Shows IP detection and DNS update activity

# Manually trigger DDNS update
sudo systemctl start ddns-update.service
# Force an immediate update check
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
- Ensure `/etc/resolv.conf` points to `127.0.0.1` (rerun the role with `dns_update_resolv_conf: true` if it was overwritten)

### DDNS not updating
- Check timer status: `sudo systemctl status ddns-update.timer`
- View update logs: `sudo tail /var/log/ddns/ddns-update.log`
- Check service errors: `sudo journalctl -u ddns-update.service -n 100`
- Verify API token: `sudo cat /etc/ddns/gandi.env` (check permissions)
- Test connectivity: `curl -H "Authorization: Bearer YOUR_TOKEN" https://api.gandi.net/v5/livedns/domains/example.com`
- Manual trigger: `sudo systemctl start ddns-update.service`

### DDNS updates but DNS not resolving
- Verify records in Gandi: Check domain control panel
- Check TTL: Wait for TTL expiry (default 300 seconds)
- Test with public DNS: `dig @8.8.8.8 home.example.com`
- Verify subdomain matches: Check `dns_ddns_subdomain` variable

## Files and Directories

### DNS (Unbound)
- `/etc/unbound/unbound.conf.d/` - Unbound configuration
  - `00-base.conf` - Base Unbound settings
  - `05-forward-zones.conf` - Forward zone configuration (when `dns_forward_zones` is set)
  - `10-split-dns.conf` - Split-horizon views
- `/var/lib/unbound/` - Blocklists and data
- `/usr/local/bin/update-blocklists.sh` - Blocklist update script
- `/etc/systemd/system/unbound-blocklist.*` - Update timer and service

### DDNS (when enabled)
- `/usr/local/bin/ddns-update.sh` - DDNS update script
- `/etc/ddns/gandi.env` - Gandi API token (0600 permissions)
- `/var/log/ddns/ddns-update.log` - Update logs
- `/etc/systemd/system/ddns-update.service` - DDNS service unit
- `/etc/systemd/system/ddns-update.timer` - DDNS timer unit

## License

MIT

## Author

Ansible Role for DNS deployment with split-horizon and ad blocking
