# homelab_deploy

Ansible role to deploy the Homelab Django application with dual router Traefik authentication.

## Description

This role deploys the Homelab service, a Django application for managing home infrastructure and services. It provides:

- Django application with SQLite database
- Granian WSGI server
- Rsync deployment from local source (development workflow)
- Dual router Traefik authentication (no auth on LAN/Tailscale, basic auth on public)
- Static file and media management
- Systemd service configuration

**Note:** This role only supports rsync deployment from a local source directory. Unlike some other services, homelab does not support git-based deployment.

## Requirements

- Ubuntu/Debian-based target system
- Python 3.12+ installed
- uv package manager installed globally at `/usr/local/bin/uv`
- Traefik reverse proxy installed (optional, but recommended)
- Ansible 2.9+
- Required collection: `ansible.posix` (for synchronize/rsync module)
- Local source directory with homelab code (for rsync deployment)

## Role Variables

### Required Variables

These variables MUST be set when using this role:

```yaml
homelab_source_path: ""         # Local path to Homelab source code
homelab_secret_key: ""          # Django secret key (generate with: openssl rand -hex 32)
```

### Required for Traefik Basic Auth

When `homelab_basic_auth_enabled: true` (default), you must also provide:

```yaml
homelab_basic_auth_password: ""  # Plain text password for basic auth
```

### Common Configuration

Frequently modified settings with sensible defaults:

```yaml
# Application settings
homelab_app_port: 10010
homelab_app_host: "127.0.0.1"
homelab_workers: 4

# Django settings
homelab_django_settings_module: "config.settings.production"
homelab_django_allowed_hosts: "127.0.0.1"
homelab_django_debug: false

# Traefik configuration
homelab_traefik_enabled: true
homelab_traefik_host: "home.example.com"

# Traefik dual router authentication
homelab_basic_auth_enabled: true
homelab_basic_auth_user: "admin"

# Internal network IP ranges (for dual router pattern)
homelab_internal_ip_ranges:
  - "192.168.0.0/16"      # RFC1918 private
  - "10.0.0.0/8"          # RFC1918 private
  - "172.16.0.0/12"       # RFC1918 private
  - "100.64.0.0/10"       # Tailscale CGNAT
  - "fd7a:115c:a1e0::/48" # Tailscale IPv6
  - "fd50:3e45:c454:0::/64" # ULA IPv6
  - "2a02:3100:3d40:9c00::/64" # ISP IPv6 (customize per deployment)
```

### Advanced Configuration

```yaml
# User and paths
homelab_user: homelab
homelab_group: "{{ homelab_user }}"
homelab_home: /home/{{ homelab_user }}
homelab_site_path: "{{ homelab_home }}/site"

# Database
homelab_database_path: "{{ homelab_site_path }}/db.sqlite3"

# Static and media
homelab_static_root: "{{ homelab_site_path }}/staticfiles"
homelab_media_root: "{{ homelab_site_path }}/media"
homelab_media_subdirs:
  - services
  - services/logos

# Service restart behavior
homelab_service_restart_on_change: true
```

For a complete list of variables, see `defaults/main.yml`.

## Dependencies

None.

## Example Playbook

### Basic Usage

```yaml
---
- name: Deploy Homelab
  hosts: macmini
  become: true
  vars:
    secrets: "{{ lookup('community.sops.sops', 'secrets/prod/homelab.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.homelab_deploy
      vars:
        homelab_source_path: "/Users/jochen/projects/homelab"
        homelab_secret_key: "{{ secrets.django_secret_key }}"
        homelab_basic_auth_password: "{{ secrets.traefik_basic_auth_password }}"
        homelab_traefik_host: "home.xn--wersdrfer-47a.de"
        homelab_django_allowed_hosts: "127.0.0.1,home.xn--wersdrfer-47a.de"
```

### Disable Basic Auth (Single Router)

```yaml
---
- name: Deploy Homelab without Basic Auth
  hosts: macmini
  become: true
  vars:
    secrets: "{{ lookup('community.sops.sops', 'secrets/prod/homelab.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.homelab_deploy
      vars:
        homelab_source_path: "/Users/jochen/projects/homelab"
        homelab_secret_key: "{{ secrets.django_secret_key }}"
        homelab_traefik_host: "home.xn--wersdrfer-47a.de"
        homelab_django_allowed_hosts: "127.0.0.1,home.xn--wersdrfer-47a.de"
        homelab_basic_auth_enabled: false
```

### Custom Internal IP Ranges

```yaml
---
- name: Deploy Homelab with Custom IP Ranges
  hosts: macmini
  become: true
  vars:
    secrets: "{{ lookup('community.sops.sops', 'secrets/prod/homelab.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.homelab_deploy
      vars:
        homelab_source_path: "/Users/jochen/projects/homelab"
        homelab_secret_key: "{{ secrets.django_secret_key }}"
        homelab_basic_auth_password: "{{ secrets.traefik_basic_auth_password }}"
        homelab_traefik_host: "home.example.com"
        homelab_django_allowed_hosts: "127.0.0.1,home.example.com"
        homelab_internal_ip_ranges:
          - "192.168.1.0/24"  # Your specific LAN
          - "100.64.0.0/10"   # Tailscale
          - "2001:db8::/32"   # Your IPv6 prefix
```

## Dual Router Authentication Pattern

### How It Works

The role implements a dual router pattern in Traefik:

1. **Internal Router** (priority 120, higher)
   - Matches: ClientIP in `homelab_internal_ip_ranges`
   - Authentication: NONE
   - Use case: LAN and Tailscale access without auth prompts

2. **External Router** (priority 100, lower)
   - Matches: All other IPs (public internet)
   - Authentication: HTTP Basic Auth
   - Use case: Secure public access

### Network Ranges

Default internal IP ranges include:

- **RFC1918 Private**: `192.168.0.0/16`, `10.0.0.0/8`, `172.16.0.0/12`
- **Tailscale IPv4**: `100.64.0.0/10` (CGNAT range)
- **Tailscale IPv6**: `fd7a:115c:a1e0::/48` (example, customize per deployment)
- **ULA IPv6**: `fd50:3e45:c454:0::/64` (example, customize per deployment)
- **ISP IPv6**: `2a02:3100:3d40:9c00::/64` (example, customize per deployment)

**Important**: Update the IPv6 prefixes to match your actual network configuration!

To find your IPv6 prefixes:
```bash
ip -6 addr show | grep "scope global"
```

### Testing the Dual Router

After deployment, test from different networks:

```bash
# From LAN - should not prompt for auth
curl -I https://home.example.com

# From Tailscale - should not prompt for auth
curl -I https://home.example.com

# From public (LTE/external) - should return 401 without auth
curl -I https://home.example.com

# From public with auth - should return 200
curl -u admin:password -I https://home.example.com
```

Check Traefik logs to verify router matching:

```bash
journalctl -u traefik -f
# Look for: RouterName=homelab-int (internal) or RouterName=homelab-ext (external)
# Verify ClientAddr shows your real IP, not a gateway IP
```

## Architecture

### Deployment Flow

1. **User and Directories**: Create homelab user and directory structure
2. **Source Sync**: Rsync Django source from local machine
3. **Python Environment**: Create venv with uv and install dependencies
4. **Django Setup**: Run migrations, collect static files, add default services
5. **Systemd Service**: Configure and start Granian WSGI server
6. **Traefik Config**: Deploy dual router configuration

### File Structure on Target

```
/home/homelab/
├── site/
│   ├── src/                # Django application source
│   ├── manage.py           # Django management script
│   ├── pyproject.toml      # Python dependencies
│   ├── uv.lock             # Locked dependencies
│   ├── .env                # Environment configuration
│   ├── .venv/              # Virtual environment
│   ├── venv -> .venv       # Symlink for compatibility
│   ├── db.sqlite3          # SQLite database
│   ├── staticfiles/        # Collected static files
│   ├── media/              # User-uploaded media
│   └── cache/              # Django cache directory
```

## Troubleshooting

### Service Won't Start

Check the systemd service status:

```bash
systemctl status homelab
journalctl -u homelab -n 50
```

Common issues:
- Missing uv binary at `/usr/local/bin/uv`
- Database permission problems
- Port 10010 already in use

### Traefik Not Routing

Verify Traefik configuration:

```bash
cat /etc/traefik/dynamic/homelab.yml
journalctl -u traefik -f
```

Check that:
- Traefik service is running
- DNS resolves to correct IP
- Port 443 is accessible
- Let's Encrypt certificate was issued

### Basic Auth Not Working

Verify password hash generation:

```bash
echo 'password' | htpasswd -nBi admin | cut -d: -f2
```

Check Traefik logs for auth failures:

```bash
journalctl -u traefik -f | grep -i auth
```

### Wrong Router Matching

If clients from LAN/Tailscale hit the external router:

1. **Verify Traefik sees real client IPs**:
   ```bash
   tail -f /var/log/traefik/access.log | jq -r '.ClientAddr'
   ```

2. **Check your actual IP ranges**:
   ```bash
   ip addr show
   ip -6 addr show | grep "scope global"
   ```

3. **Update `homelab_internal_ip_ranges`** to match your network

### Static Files Not Loading

Ensure static files are collected:

```bash
sudo -u homelab bash -c "cd /home/homelab/site && source .venv/bin/activate && python manage.py collectstatic --noinput"
```

Check permissions:

```bash
ls -la /home/homelab/site/staticfiles
```

## Security Considerations

### Secret Management

- **Never commit secrets** to version control
- Use SOPS or Ansible Vault for `homelab_secret_key` and `homelab_basic_auth_password`
- Generate strong secrets:
  ```bash
  openssl rand -hex 32  # Django secret key
  openssl rand -base64 16  # Basic auth password
  ```

### Systemd Hardening

The role applies systemd security hardening:
- `NoNewPrivileges=true`
- `PrivateTmp=true`
- `ProtectSystem=strict`
- `ProtectHome=true`
- Limited write access to application directories

### Database Security

- SQLite database file has 0644 permissions (user-only write)
- Located within user home directory
- Not accessible via web server (served by Django)

## Tags

No tags defined. Run the entire role.

## License

MIT

## Author Information

Created for homelab infrastructure automation.

## Changelog

### v0.1.0 (2025-10-07)

- Initial implementation
- Django/Granian/SQLite deployment
- Rsync deployment method
- Dual router Traefik authentication
- IPv4 and IPv6 support
- Systemd service with security hardening
- Static file and media management

## Related Roles

- `traefik_deploy` - Deploy Traefik reverse proxy
- `nyxmon_deploy` - Similar Django/SQLite deployment pattern
- `fastdeploy_deploy` - Django deployment with PostgreSQL

## References

- [Django Documentation](https://docs.djangoproject.com/)
- [Traefik Documentation](https://doc.traefik.io/traefik/)
- [Traefik ClientIP Matcher](https://doc.traefik.io/traefik/routing/routers/#clientip)
- [Granian WSGI Server](https://github.com/emmett-framework/granian)
