# Traefik Deploy Role

Ansible role to deploy Traefik reverse proxy with Let's Encrypt automatic certificate management.

## Description

This role installs and configures the base Traefik infrastructure on a target host. It handles:

- Downloading and installing the Traefik binary
- Creating the directory structure (`/etc/traefik`, `/etc/traefik/dynamic`, `/etc/traefik/acme`, `/var/log/traefik`)
- Deploying static configuration with HTTP→HTTPS redirect
- Setting up Let's Encrypt automatic certificate management
- Configuring the systemd service with security hardening
- Setting up log rotation
- Optionally configuring firewall rules

**Note**: This role only handles the base Traefik infrastructure. Individual service configurations should be managed by their respective roles using Traefik's dynamic configuration in `/etc/traefik/dynamic/`.

## Requirements

- Target system: Linux (Debian/Ubuntu recommended)
- Root/sudo access
- Ports 80 and 443 available and accessible from the internet (for Let's Encrypt HTTP challenge)
- Valid email address for Let's Encrypt registration

## Role Variables

### Required Variables

```yaml
# Let's Encrypt email (REQUIRED - must be set in playbook)
traefik_letsencrypt_email: "admin@example.com"
```

### Optional Variables

#### Version and Platform

```yaml
# Traefik version to install
traefik_version: "3.3.5"

# Platform configuration (auto-detected from ansible facts)
# Only override if auto-detection fails or for cross-platform deployment
traefik_os: "linux"       # auto-detected from ansible_system
traefik_arch: "amd64"     # auto-detected from ansible_architecture
#                           x86_64 → amd64, aarch64 → arm64, armv7l → arm

# Checksum validation (RECOMMENDED for production)
# Get from https://github.com/traefik/traefik/releases
traefik_checksum: ""      # Empty = skip validation
# Example: "sha256:abc123..."

# Force update even if version matches
traefik_force_update: false
```

#### Directory Configuration

```yaml
traefik_config_dir: /etc/traefik
traefik_dynamic_dir: "{{ traefik_config_dir }}/dynamic"
traefik_acme_dir: "{{ traefik_config_dir }}/acme"
traefik_log_dir: /var/log/traefik
traefik_binary_path: /usr/local/bin/traefik
```

#### Logging

```yaml
traefik_log_level: "INFO"      # DEBUG, INFO, WARN, ERROR
traefik_log_format: "json"     # json or common
traefik_logrotate_days: 7
```

#### Dashboard & API

```yaml
traefik_dashboard_enabled: true
traefik_dashboard_port: 8090    # Moved from 8080 to avoid UniFi conflict

# Dashboard firewall access (default: internal only)
traefik_dashboard_firewall_open: false
```

**Dashboard Access Options:**

1. **SSH Tunnel (Recommended)**: `ssh -L 8090:localhost:8090 your-server`
2. **Firewall Open (Security Risk)**: Set `traefik_dashboard_firewall_open: true`
3. **Via Traefik HTTPS**: Create dynamic config to expose with authentication

#### Entrypoints

```yaml
traefik_http_port: 80
traefik_https_port: 443
traefik_http_redirect_to_https: true
```

#### Features

```yaml
traefik_metrics_enabled: true   # Prometheus metrics
traefik_configure_firewall: true
```

## Dependencies

None.

## Example Playbook

### Basic Usage

```yaml
---
- name: Deploy Traefik
  hosts: webservers
  become: true
  roles:
    - role: local.ops_library.traefik_deploy
      vars:
        traefik_letsencrypt_email: "admin@example.com"
```

### Production Deployment with Checksum

```yaml
---
- name: Deploy Traefik with Checksum Validation
  hosts: webservers
  become: true
  roles:
    - role: local.ops_library.traefik_deploy
      vars:
        traefik_version: "3.3.5"
        traefik_letsencrypt_email: "admin@example.com"
        traefik_checksum: "sha256:1234567890abcdef..."
```

### ARM64 Architecture

Architecture is auto-detected, but you can override if needed:

```yaml
---
- name: Deploy Traefik on ARM64
  hosts: arm_servers
  become: true
  roles:
    - role: local.ops_library.traefik_deploy
      vars:
        traefik_letsencrypt_email: "admin@example.com"
        # traefik_arch auto-detected from ansible_architecture
        # Override only if needed: traefik_arch: "arm64"
```

### Upgrade to New Version

Simply change the `traefik_version` variable:

```yaml
---
- name: Upgrade Traefik
  hosts: webservers
  become: true
  roles:
    - role: local.ops_library.traefik_deploy
      vars:
        traefik_version: "3.4.0"  # Role will detect version mismatch and upgrade
        traefik_letsencrypt_email: "admin@example.com"
        traefik_checksum: "sha256:newversion..."
```

## Service Configuration

After deploying Traefik, create dynamic configurations in `/etc/traefik/dynamic/` for your services.

### Example: Simple HTTPS Service

Create `/etc/traefik/dynamic/myapp.yml`:

```yaml
http:
  routers:
    myapp:
      rule: "Host(`myapp.example.com`)"
      entryPoints: [web-secure]
      service: myapp
      tls:
        certResolver: letsencrypt

  services:
    myapp:
      loadBalancer:
        servers:
          - url: "http://localhost:8000"
```

Traefik automatically watches this directory and reloads configurations.

### Use certbot-managed certificates (file provider)

```yaml
- role: local.ops_library.traefik_deploy
  vars:
    traefik_letsencrypt_email: "admin@example.com"
    traefik_file_certificates:
      - cert_file: "/etc/letsencrypt/live/home.xn--wersdrfer-47a.de/fullchain.pem"
        key_file: "/etc/letsencrypt/live/home.xn--wersdrfer-47a.de/privkey.pem"
```

Place this under `/etc/traefik/dynamic/certificates.yml`; Traefik reloads it automatically when the cert is renewed.

## Dual Router Authentication Pattern

For implementing the dual router pattern (internal vs external authentication), see the example in homelab service configuration.

## Architecture Support

This role **automatically detects** the target platform from Ansible facts:

- `ansible_system` → `traefik_os` (Linux → linux, Darwin → darwin)
- `ansible_architecture` → `traefik_arch` (x86_64 → amd64, aarch64 → arm64)

Supported platforms:

| OS      | Architecture | Auto-detect | Tested |
|---------|-------------|-------------|--------|
| Linux   | amd64       | ✅          | ✅     |
| Linux   | arm64       | ✅          | ⚠️     |
| Linux   | arm         | ✅          | ❌     |
| Darwin  | amd64       | ✅          | ❌     |
| Darwin  | arm64       | ✅          | ❌     |

Override `traefik_os` and `traefik_arch` only if auto-detection fails.

## Security Considerations

### Checksum Validation

**Always use checksum validation in production:**

1. Visit https://github.com/traefik/traefik/releases/tag/v3.3.5
2. Download `traefik_v3.3.5_checksums.txt`
3. Find the SHA256 hash for your platform
4. Set in playbook: `traefik_checksum: "sha256:abc123..."`

### Dashboard Security

The dashboard is **NOT exposed** through the firewall by default (internal localhost access only).

**Secure access methods:**

1. **SSH Tunnel** (Recommended):
   ```bash
   ssh -L 8090:localhost:8090 user@server
   # Access at http://localhost:8090
   ```

2. **Traefik Dynamic Config with Auth**:
   Create `/etc/traefik/dynamic/dashboard.yml`:
   ```yaml
   http:
     routers:
       dashboard:
         rule: "Host(`traefik.example.com`)"
         entryPoints: [web-secure]
         service: api@internal
         middlewares: [dashboard-auth]
         tls:
           certResolver: letsencrypt

     middlewares:
       dashboard-auth:
         basicAuth:
           users:
             - "admin:$apr1$..." # htpasswd hash
   ```

3. **Open Firewall** (Not Recommended):
   ```yaml
   traefik_dashboard_firewall_open: true  # ⚠️ Security risk!
   ```

### Systemd Hardening

The role applies systemd security hardening:
- `NoNewPrivileges=true`
- `PrivateTmp=true`
- `ProtectSystem=strict`
- `ProtectHome=true`
- Limited write access to `/etc/traefik` and `/var/log/traefik`

## Monitoring

### Prometheus Metrics

Metrics are exposed on the dashboard port:

```bash
curl http://localhost:8090/metrics
```

Configure Prometheus to scrape:

```yaml
scrape_configs:
  - job_name: 'traefik'
    static_configs:
      - targets: ['localhost:8090']
```

### Logs

```bash
# Traefik logs
journalctl -u traefik -f

# Access logs
tail -f /var/log/traefik/access.log

# Error logs
tail -f /var/log/traefik/traefik.log
```

## Troubleshooting

### Let's Encrypt Certificate Issues

1. **Port 80 not accessible**:
   - Ensure firewall allows port 80 (HTTP challenge)
   - Check router port forwarding

2. **Rate limiting**:
   - Let's Encrypt has rate limits (5 certificates per week per domain)
   - Use staging environment for testing: https://letsencrypt.org/docs/staging-environment/

3. **Check ACME logs**:
   ```bash
   journalctl -u traefik | grep -i acme
   ```

### Version Upgrade Not Working

If version upgrade is skipped:

```bash
# Force upgrade
ansible-playbook playbook.yml -e traefik_force_update=true
```

### Dashboard Not Accessible

1. **Check service is running**:
   ```bash
   systemctl status traefik
   ```

2. **Verify port is listening**:
   ```bash
   netstat -tlnp | grep 8090
   ```

3. **Access via SSH tunnel**:
   ```bash
   ssh -L 8090:localhost:8090 user@server
   # Then visit http://localhost:8090
   ```

## Tags

No tags defined. Run the entire role.

## License

MIT

## Author Information

Created for homelab infrastructure automation.

## Changelog

### v0.1.0 (2025-10-07)

- Initial implementation
- Traefik v3.3.5 support
- Let's Encrypt HTTP challenge
- Systemd service with security hardening
- Automatic version detection and upgrade
- Multi-architecture support (amd64, arm64)
- Checksum validation
- Dashboard firewall controls
- Log rotation configuration

## Related Roles

- `traefik_config` - Manage Traefik dynamic configurations (planned)
- Service-specific deploy roles handle their own Traefik configs

## References

- [Traefik Documentation](https://doc.traefik.io/traefik/)
- [Let's Encrypt](https://letsencrypt.org/)
- [Traefik GitHub Releases](https://github.com/traefik/traefik/releases)
