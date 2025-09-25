# DNS Deploy Role

Deploy and configure a complete DNS solution using Pi-hole v6 and Unbound for local service discovery and ad blocking.

> **Note**: This role has been thoroughly tested and refined to handle Pi-hole v6's new architecture and Unbound's zone type limitations. It provides a robust solution that supports both wildcard DNS and custom host overrides simultaneously.

## Features

- **Simple Mode** (default): Pi-hole with Unbound providing both wildcard DNS and custom host overrides
- **Advanced Mode**: Unbound split-DNS with different responses for LAN vs Tailscale clients
- Ad blocking via Pi-hole v6 with customizable blocklists
- Wildcard DNS for Traefik-backed services (using Unbound redirect zones)
- Custom DNS entries for non-Traefik services (using Unbound static zones)
- IDN/Punycode support for domains with umlauts
- Clean install option for handling existing DNS configurations
- Automatic backup of existing configurations
- Full support for both wildcards AND custom hosts simultaneously

## Requirements

- Ubuntu 20.04+ or Debian 10+
- Root or sudo access
- Network connectivity for package installation

## Quick Start

### Simple Mode (Default)

```yaml
- hosts: dns_server
  become: true
  roles:
    - role: local.ops_library.dns_deploy
      vars:
        dns_local_domain: "home.example.com"
        dns_local_domain_punycode: "home.example.com"  # Same if no special chars
        dns_custom_entries:
          - { name: "router.home.example.com", ip: "192.168.1.1" }
          - { name: "nas.home.example.com", ip: "192.168.1.10" }
```

### Advanced Mode (Split-DNS)

```yaml
- hosts: dns_server
  become: true
  roles:
    - role: local.ops_library.dns_deploy
      vars:
        dns_mode: "advanced"
        dns_local_domain: "home.example.com"
        dns_local_domain_punycode: "home.example.com"
        dns_split_tailscale_ip: "100.64.0.5"  # Required for advanced mode
        dns_split_services:
          - { name: "router", lan_ip: "192.168.1.1", tailscale_ip: "192.168.1.1" }
```

## Architecture

### Simple Mode
```
Client → Pi-hole (port 53) → Unbound (port 5335) → Internet
                              ↓
                              Unbound handles local resolution:
                              - redirect zone: *.home.example.com → Traefik IP
                              - static zones: router.home.example.com → specific IP
```

### Advanced Mode
```
LAN Client → Pi-hole → Unbound (views) → Returns LAN IP
Tailscale Client → Pi-hole → Unbound (views) → Returns Tailscale IP
```

### How Wildcard + Custom Hosts Work Together

The role uses a clever combination of Unbound zone types:
1. **Base domain** uses `redirect` zone - catches all undefined subdomains
2. **Custom hosts** use `static` zones - override the redirect for specific hosts
3. Unbound processes more specific zones first, so custom hosts take precedence

## Role Variables

### Core Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `dns_mode` | `"simple"` | Deployment mode: `"simple"` or `"advanced"` |
| `dns_local_domain` | `"home.example.com"` | Local domain for services |
| `dns_local_domain_punycode` | `"home.example.com"` | IDN encoded version (same if no special chars) |
| `dns_local_ip` | `{{ ansible_default_ipv4.address }}` | IP for wildcard resolution |
| `dns_clean_install` | `false` | Remove existing DNS configs before deployment |
| `dns_backup_existing` | `true` | Backup existing configs before removal |

### Pi-hole Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `dns_pihole_web_interface` | `false` | Enable/disable web UI |
| `dns_pihole_web_password` | `""` | Password for web UI |
| `dns_pihole_ftl_port` | `4711` | FTL API port |

### Unbound Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `dns_unbound_port` | `5335` | Unbound listening port |
| `dns_unbound_upstream` | Cloudflare, Google | Upstream DNS servers |

### Simple Mode Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `dns_custom_entries` | Router, Proxmox, Pi-hole | Custom DNS entries |
| `dns_dnsmasq_local_ttl` | `86400` | TTL for local records |

### Advanced Mode Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `dns_split_lan_network` | `"192.168.178.0/24"` | LAN network range |
| `dns_split_tailscale_network` | `"100.64.0.0/10"` | Tailscale network range |
| `dns_split_tailscale_ip` | `""` | **Required** - Tailscale IP |
| `dns_split_services` | Router, Proxmox | Service-specific IPs |

### Ad Blocking

| Variable | Default | Description |
|----------|---------|-------------|
| `dns_blocklists_enabled` | `true` | Enable ad blocking |
| `dns_blocklists` | Various lists | Blocklist URLs |
| `dns_whitelist_domains` | GitHub, PyPI, etc. | Whitelisted domains |

### System Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `dns_configure_local_resolver` | `true` | Update /etc/resolv.conf |
| `dns_firewall_enable` | `true` | Configure UFW rules |

## Service Discovery

### Traefik-Backed Services
Services behind Traefik require no DNS configuration - the wildcard handles everything:
- `service.home.example.com` → Traefik IP → Traefik routes to service

### Non-Traefik Services
Use `dns_custom_entries` (Simple) or `dns_split_services` (Advanced) for services that need specific IPs:
- Router, switches, printers
- Services on different hosts
- Services not behind Traefik

## Testing

After deployment, verify DNS resolution:

```bash
# Test wildcard resolution
dig @dns-server test.home.example.com

# Test custom entry
dig @dns-server router.home.example.com

# Test ad blocking
dig @dns-server doubleclick.net  # Should return 0.0.0.0 or NXDOMAIN

# Test external resolution
dig @dns-server google.com

# Advanced Mode: Test split-DNS
dig @dns-server +subnet=192.168.1.0/24 service.home.example.com  # LAN IP
dig @dns-server +subnet=100.64.0.0/10 service.home.example.com   # Tailscale IP
```

## Troubleshooting

### Port 53 already in use
- The role automatically stops systemd-resolved early in deployment
- If still issues, check: `sudo lsof -i :53`
- Manual fix: `sudo systemctl stop systemd-resolved && sudo systemctl disable systemd-resolved`

### Services not resolving
- Simple Mode: Check `/etc/unbound/unbound.conf.d/10-local-simple.conf`
- Advanced Mode: Check `/etc/unbound/unbound.conf.d/10-split-dns.conf`
- Restart services: `sudo systemctl restart unbound && sudo systemctl restart pihole-FTL`
- Test Unbound directly: `dig @127.0.0.1 -p 5335 test.home.example.com`

### Wildcards not working after remove/deploy
- The role now includes immediate Unbound restart to prevent this
- Manual fix: `sudo systemctl restart unbound`
- Verify config is active: `sudo unbound-checkconf`

### No ad blocking
- Check blocklists: `pihole -q doubleclick.net`
- Update gravity: `pihole -g`
- Verify upstream DNS: `grep upstreams /etc/pihole/pihole.toml` (should show `127.0.0.1#5335`)

### Wrong IP from Tailscale (Advanced Mode)
- Verify `dns_split_tailscale_ip` is set
- Test: `dig @localhost +subnet=100.64.0.1/32 service.home.example.com`

### Trust anchor issues
- The role automatically cleans and regenerates trust anchors
- Manual fix: `sudo rm /var/lib/unbound/root.key && sudo unbound-anchor`

### Deployment on Existing DNS Server

If deploying on a system with existing DNS services:

1. **Option A: Clean Install (Recommended)**
   ```yaml
   - role: local.ops_library.dns_deploy
     vars:
       dns_clean_install: true  # Removes conflicting configs
   ```

2. **Option B: Remove First**
   ```bash
   # Remove existing DNS completely
   just remove-dns
   # Then deploy fresh
   just deploy-one dns
   ```

3. **Option C: Manual Cleanup**
   ```bash
   # On target server
   sudo rm -rf /etc/unbound/unbound.conf.d/*
   sudo rm -f /var/lib/unbound/root.key
   sudo unbound-anchor -a /var/lib/unbound/root.key
   ```

## Known Issues and Solutions

### Pi-hole v6 Changes
- **Issue**: Pi-hole v6 uses TOML configuration instead of setupVars.conf
- **Solution**: Role handles both formats and configures upstream DNS in pihole.toml

### Unbound Zone Limitations
- **Issue**: No single Unbound zone type supports both wildcards and custom hosts
- **Solution**: Combination of `redirect` zone for base domain and `static` zones for overrides

### systemd-resolved Port Conflicts
- **Issue**: systemd-resolved blocks port 53 on Ubuntu systems
- **Solution**: Early stopping of systemd-resolved in deployment process

### Configuration Timing
- **Issue**: Unbound config changes require restart before verification
- **Solution**: Immediate restart after configuration changes in Simple mode

## Removal

To completely remove DNS services, use the companion `dns_remove` role:

```yaml
- role: local.ops_library.dns_remove
  vars:
    dns_confirm_removal: true
    dns_remove_pihole_data: true  # Also remove data/blocklists
    dns_restore_systemd_resolved: true  # Restore system DNS
```

Or use the ops-control command:
```bash
just remove-dns
```

## License

MIT

## Author

Ansible DNS Deploy Role for ops-library