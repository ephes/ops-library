# DNS Deploy Role

Deploy Unbound DNS with split-horizon views and ad blocking for homelab environments.

## Features

- **Split-horizon DNS**: Different responses for LAN vs Tailscale clients
- **Ad blocking**: Via customizable blocklists (hosts and AdGuard syntax)
- **Wildcard DNS**: For Traefik-backed services (`*.home.example.com`)
- **Custom DNS entries**: Service-specific overrides
- **IDN/Punycode support**: For domains with special characters
- **Automatic blocklist updates**: Via systemd timer
- **DNSSEC validation**: For secure DNS resolution
- **Dynamic DNS (DDNS)**: Optional updater with pluggable provider backends (Gandi LiveDNS and RFC 2136/TSIG implemented, several at once for migrations), failing loudly and exposing a status file for monitoring (opt-in)

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

### Unbound Behavior

| Variable | Default | Description |
|----------|---------|-------------|
| `dns_unbound_serve_expired` | `false` | Serve stale cached answers during upstream outages |
| `dns_unbound_serve_expired_ttl` | `86400` | Maximum age of stale entries served to clients |
| `dns_unbound_serve_expired_reply_ttl` | `30` | TTL returned to clients for stale answers |
| `dns_unbound_serve_expired_ttl_reset` | `false` | Keep stale entries eligible during repeated upstream refresh failures |
| `dns_unbound_serve_expired_client_timeout` | `0` | Optional RFC 8767 delay before replying with stale data |
| `dns_unbound_prefetch` | `false` | Refresh hot cache entries before expiry to reduce outage misses |
| `dns_unbound_prefetch_key` | `false` | Prefetch DNSKEY material to reduce DNSSEC latency for hot names |
| `dns_unbound_num_queries_per_thread` | `0` | Override recursion queue depth per thread (0 keeps Unbound's default) |
| `dns_unbound_disable_distro_resolvconf_integration` | `true` | Disable Ubuntu's Unbound/resolvconf helper when the role manages `/etc/resolv.conf` |

When `dns_unbound_serve_expired` is enabled, Unbound can keep answering from cache during brief upstream failures instead of immediately returning `SERVFAIL` for expired records. This is still partial protection: uncached names, newer RR types such as `HTTPS`, or overloaded recursion queues can still fail during a WAN outage. For outage-prone links, pair stale serving with `dns_unbound_prefetch`, `dns_unbound_serve_expired_ttl_reset`, and a larger `dns_unbound_num_queries_per_thread`.

### Split-DNS Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `dns_split_lan_network` | `"192.168.0.0/16"` | LAN network range |
| `dns_split_tailscale_network` | `"100.64.0.0/10"` | Tailscale network range |
| `dns_split_lan_ipv6_networks` | `[]` | Optional LAN IPv6 ranges (e.g., `["fdxx:...::/64"]`) |
| `dns_split_tailscale_ipv6_networks` | `[]` | Optional Tailscale IPv6 ranges (e.g., `["fdxx:...::/48"]`) |
| `dns_split_lan_ip` | `{{ ansible_default_ipv4.address }}` | IP returned for LAN clients |
| `dns_split_tailscale_ip` | `""` | IP returned for Tailscale clients |
| `dns_split_services` | `[]` | Service-specific IP overrides |

### Blocklist Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `dns_blocklists_enabled` | `true` | Enable ad blocking |
| `dns_blocklists` | See defaults | List of blocklist URLs |
| `dns_allowlist` | `["github.com", ...]` | Domains never to block |

Supported upstream blocklist formats are hosts-style entries (for example `0.0.0.0 example.com`) and AdGuard-style rules (for example `||example.com^`). Plain one-domain-per-line feeds are not parsed by the generated updater script.

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

**Example - Forward all other queries to public resolvers:**

```yaml
dns_forward_zones:
  - name: "."
    forward_addrs:
      - "1.1.1.1"
      - "1.0.0.1"
      - "8.8.8.8"
      - "8.8.4.4"
    forward_first: true
  - name: "fritz.box"
    forward_addrs:
      - "192.168.178.1"
```

For the root zone `.`, `forward_first: true` lets Unbound fall back to direct recursion if the configured forwarders are unavailable but general internet connectivity still works. Keep `forward_first: false` for private-only forwarded zones like `fritz.box` or `tailde2ec.ts.net`.

**Example - LAN/Tailscale IPv6 view mapping:**

```yaml
dns_split_lan_ipv6_networks:
  - "fd50:3e45:c454::/64"
dns_split_tailscale_ipv6_networks:
  - "fd7a:115c:a1e0::/48"
```

### Local DNS Records

Local records are served authoritatively by Unbound before forwarded zones. Use them for critical hostnames inside forwarded domains when router or DHCP registration is unreliable.

| Variable | Default | Description |
|----------|---------|-------------|
| `dns_local_records` | `[]` | List of static DNS records served directly by Unbound |

Each local record entry supports:

| Key | Required | Description |
|-----|----------|-------------|
| `name` | Yes | Fully-qualified hostname (e.g., `"macmini.fritz.box"`) |
| `type` | Yes | DNS record type (e.g., `"A"`, `"AAAA"`) |
| `value` | Yes | Record value |

**Example - Pin a critical host inside a forwarded router zone:**

```yaml
dns_local_records:
  - name: "macmini.fritz.box"
    type: "A"
    value: "192.168.178.94"
```

Notes:
- Use leaf hostnames like `macmini.fritz.box`, not zone apex names like `fritz.box`.
- A local record whose `name` exactly matches a forwarded zone apex would shadow the forwarded zone.
- Supported record types are `A`, `AAAA`, `CNAME`, `TXT`, `MX`, `PTR`, and `SRV`.

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
| `dns_ddns_provider` | `"gandi"` | Provider backend: `gandi` or `rfc2136` |
| `dns_ddns_providers` | `[]` | Write several providers in one run, e.g. `["gandi", "rfc2136"]` while a delegation moves; empty means `[dns_ddns_provider]` |
| `dns_ddns_domain` | `"CHANGEME"` | Zone (e.g., `"example.com"`; IDN names are converted to punycode) |
| `dns_ddns_subdomain` | `"home"` | Subdomain to update |
| `dns_ddns_update_wildcard` | `true` | Also update `*.subdomain` |
| `dns_ddns_ttl` | `300` | DNS record TTL in seconds |
| `dns_ddns_interval` | `"5min"` | Update check interval |
| `dns_ddns_ipv4_enabled` | `true` | Update IPv4 (A records) |
| `dns_ddns_ipv6_enabled` | `true` | Update IPv6 (AAAA records) |
| `dns_ddns_ipv4_source_url` / `dns_ddns_ipv6_source_url` | icanhazip | WAN address detection |
| `dns_ddns_verify_nameservers` | `[]` | Nameservers asked for the public view (empty: the zone's NS records) |
| `dns_ddns_state_dir` | `"/var/lib/ddns"` | Dedicated state directory (basename must contain `ddns`) |
| `dns_ddns_status_path` | `"{{ dns_ddns_state_dir }}/status.json"` | Status file written by every run |
| `dns_ddns_script_path` | `"/usr/local/bin/ddns-update"` | Updater (Python 3, stdlib only) |
| `dns_ddns_log_max_size_mb` | `10` | Log rotation size in MB |
| `dns_ddns_api_token` | `"CHANGEME"` | Gandi credential: Personal Access Token or legacy API key |
| `dns_ddns_gandi_auth_scheme` | `"bearer"` | `bearer` for a PAT, `apikey` for a legacy API key |
| `dns_ddns_rfc2136_server` / `_port` | `"CHANGEME"` / `53` | Primary nameserver that accepts the updates |
| `dns_ddns_rfc2136_key_name` / `_key_algorithm` / `_key_secret` | `"CHANGEME"` / `hmac-sha256` / `"CHANGEME"` | TSIG key; the secret comes from secrets |
| `dns_ddns_rfc2136_update_zone` | `""` | Zone to update (e.g. a delegated `home.example.com`); empty lets nsupdate find it by SOA |
| `dns_ddns_status_endpoint_enabled` | `false` | Serve the status file over authenticated HTTP |
| `dns_ddns_status_endpoint_bind` / `_port` / `_path` | Tailscale IP / `9112` / `/.well-known/ddns` | Status endpoint address |
| `dns_ddns_status_endpoint_auth_user` / `_password` | `"CHANGE_ME"` | Basic-auth credentials (required when enabled) |

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
4. Mixed hosts-style and AdGuard-style lists are accepted, and one failed download no longer aborts the whole refresh

### Wildcard Resolution

- `*.home.example.com` → Configured IP (LAN or Tailscale based on view)
- Specific services can override with `dns_split_services`

### Dynamic DNS (Optional)

When enabled (`dns_ddns_enabled: true`), `ddns-update.timer` runs
`/usr/local/bin/ddns-update --config /etc/ddns/config.json` as the `ddns` account.
Settings live in `/etc/ddns/config.json`; credentials in `/etc/ddns/credentials.env`
(mode 0600). Each run:

1. Detects the public IPv4 and IPv6 address (each must be a global address).
2. For `subdomain` and `*.subdomain`, A and AAAA: reads the record from the provider,
   writes it only when it differs, then reads it back. Every record is logged as
   `unchanged`, `updated <old> -> <new>` or `ERROR` (credentials are never logged).
3. Asks the authoritative nameservers (`dig +norecurse`) what the public sees: those
   in `dns_ddns_verify_nameservers`, or else the NS set of the closest enclosing zone
   that has one (so `home` in a delegated child zone `home.example.com` is checked at
   the child's servers once the delegation exists, and at the parent's before).
4. Writes `/var/lib/ddns/status.json`: WAN addresses, per-record provider and public
   values, `summary.run_ok`, `summary.consecutive_failures`,
   `summary.public_ok` and `summary.public_mismatch_seconds` (how long the public
   view has differed from the WAN address).
5. Exits non-zero, so the unit fails, on any non-2xx API answer, a read-back mismatch,
   a failed address detection, a missing credential or an unknown provider. A public
   mismatch alone does not fail the run (propagation lags); monitor it through the
   status file instead.

With `dns_ddns_status_endpoint_enabled: true`, `ddns-status-endpoint.service` serves the
status file (plus `meta.age_seconds`) with basic auth, by default on the Tailscale
address, port 9112, path `/.well-known/ddns`, for a Nyxmon `json-metrics` check.

The DDNS tasks are tagged `ddns`, so `--tags ddns` redeploys only the updater.

**Providers.** `gandi` (LiveDNS v5): a Personal Access Token with the LiveDNS
"Manage domain name technical configurations" permission for the zone uses
`dns_ddns_gandi_auth_scheme: bearer`; a legacy API key uses `apikey`. A PAT that
expired or was revoked answers HTTP 403 for every request.

`rfc2136`: DNS UPDATE through `nsupdate`, signed with a TSIG key, sent to
`dns_ddns_rfc2136_server`; the record is read back from the same server with
`dig +norecurse` (a wildcard owner such as `*.home` is queried literally). The secret
is passed to nsupdate on stdin as a `key` statement, never in argv or a file, and is
redacted from error output. The server needs an `update-policy` that lets the key
change exactly these owners and types, for example with `bind_authoritative_deploy`:
`grant "ddns-home" name home.example.com. A AAAA` and
`grant "ddns-home" name *.home.example.com. A AAAA`.

Several providers: with `dns_ddns_providers: ["gandi", "rfc2136"]` every record is
written to both, which keeps the old and the new DNS host correct while resolvers
still follow a cached delegation. A failure at either fails the run. `status.json`
keeps its shape (the first provider's values in `provider_values`, the worst action
in `action`) and adds `providers` and per-record `providers.<name>`.

To add a provider, subclass `Backend` in `files/ddns_update.py` (implement
`get(name, rtype)` returning the sorted values, empty when the record does not
exist, and `set(name, rtype, values)`), register it in `BACKENDS`, add its settings
to `templates/ddns-config.json.j2` under the provider name, its credentials to
`templates/ddns.env.j2`, extend the provider assert in `tasks/ddns.yml`, and add
tests with a fake transport in `tests/test_ddns_update.py`. For example, Porkbun
(API v3) would send `apikey`/`secretapikey` in the JSON body of
`dns/retrieveByNameType/<domain>/<type>/<sub>` and `dns/editByNameType/...`
(`dns/create/<domain>` when the record is missing), needs API access enabled per
domain, and requires a TTL of at least 600.

**Example configuration:**

```yaml
- role: local.ops_library.dns_deploy
  vars:
    # ... other DNS vars ...

    # Enable DDNS
    dns_ddns_enabled: true
    dns_ddns_provider: gandi
    dns_ddns_domain: "example.com"
    dns_ddns_subdomain: "home"
    dns_ddns_api_token: "{{ vault_gandi_pat }}"  # From vault/secrets
    dns_ddns_gandi_auth_scheme: bearer
    dns_ddns_status_endpoint_enabled: true
    dns_ddns_status_endpoint_auth_user: nyxmon
    dns_ddns_status_endpoint_auth_password: "{{ vault_ddns_status_password }}"
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

# Inspect stale-serving and recursion headroom after an upstream outage
sudo unbound-control stats_noreset | egrep 'total.num.expired|total.requestlist.max|total.requestlist.exceeded'
# Useful when clients reported SERVFAIL during a WAN reconnect

# Test DDNS (when enabled)
sudo systemctl status ddns-update.timer
# Should be active and show next trigger time

sudo journalctl -u ddns-update.service -n 50
# View DDNS update logs

# Check DDNS log file
sudo tail -f /var/log/ddns/ddns-update.log
# Shows IP detection and DNS update activity

sudo jq .summary /var/lib/ddns/status.json
# Last run result and public-view freshness

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

### Brief WAN outages still cause some SERVFAILs
- Check whether the failing name was already cached: `sudo unbound-control dump_cache | rg 'example.com'`
- Inspect stale-serving and queue stats: `sudo unbound-control stats_noreset | egrep 'total.num.expired|total.requestlist.exceeded'`
- Remember that `serve-expired` only helps for cached data; uncached names and some `HTTPS`/`SVCB` lookups can still fail during DSL reconnects
- Enable `dns_unbound_prefetch`, `dns_unbound_serve_expired_ttl_reset`, and tune `dns_unbound_num_queries_per_thread` on outage-prone links

### Service not resolving
- Check Unbound config: `sudo unbound-checkconf`
- View logs: `sudo journalctl -u unbound -f`
- Test from server: `dig @127.0.0.1 test.home.example.com`
- Ensure `/etc/resolv.conf` points to `127.0.0.1` (rerun the role with `dns_update_resolv_conf: true` if it was overwritten)

### DDNS not updating
- Check timer status: `sudo systemctl status ddns-update.timer`
- View update logs: `sudo tail /var/log/ddns/ddns-update.log`
- Check service errors: `sudo journalctl -u ddns-update.service -n 100`
- Check the last run: `sudo jq '.summary, .errors' /var/lib/ddns/status.json`; HTTP 403 from Gandi on every request means the PAT expired or was revoked (or a legacy API key is sent with `dns_ddns_gandi_auth_scheme: bearer`)
- Credentials file: `/etc/ddns/credentials.env` (mode 0600, owner `ddns`; never print it)
- Test the credential: `curl -H "Authorization: Bearer <PAT>"` (or `Apikey <key>`) `https://api.gandi.net/v5/livedns/domains` must answer 200
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
- `/etc/default/unbound` - Distro helper toggles; the role disables resolvconf integration here by default
- `/var/lib/unbound/` - Blocklists and data
- `/usr/local/bin/update-blocklists.sh` - Blocklist update script
- `/etc/systemd/system/unbound-blocklist.*` - Update timer and service

### DDNS (when enabled)
- `/usr/local/bin/ddns-update` - DDNS updater (Python)
- `/etc/ddns/config.json` - DDNS settings (no secrets)
- `/etc/ddns/credentials.env` - provider credentials (0600 permissions)
- `/var/lib/ddns/status.json` - status of the last run
- `/usr/local/bin/ddns_status_httpd.py`, `ddns-status-endpoint.service` - optional status endpoint
- `/var/log/ddns/ddns-update.log` - Update logs
- `/etc/systemd/system/ddns-update.service` - DDNS service unit
- `/etc/systemd/system/ddns-update.timer` - DDNS timer unit

## License

MIT

## Author

Ansible Role for DNS deployment with split-horizon and ad blocking
