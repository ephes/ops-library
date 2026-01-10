# FastDeploy Deploy Role

Deploy the FastDeploy web-based deployment platform with full database, frontend, and service management.

## Description

This role deploys FastDeploy, a web-based platform for managing service deployments. It handles the complete deployment lifecycle including:
- PostgreSQL provisioning via the shared `postgres_install` role and application migrations
- Python environment management with uv
- Frontend application building
- Systemd service configuration
- Traefik reverse proxy integration
- Initial admin user creation
- Service synchronization from filesystem

## Requirements

- Ubuntu/Debian-based target system
- Ability to install PostgreSQL (handled automatically via dependency)
- Node.js 16+ (for frontend build)
- Python 3.14+ (managed via uv; set `fastdeploy_python_version` if needed)
- ansible-core 2.20+
- Required collections:
  - `ansible.posix` (for synchronize module)
  - `community.general` (for PostgreSQL modules)

## Role Variables

### Required Variables

These variables MUST be set when using this role:

```yaml
fastdeploy_source_path: ""         # Local path to FastDeploy source code
fastdeploy_secret_key: ""          # Django secret key (generate with: openssl rand -hex 32)
fastdeploy_initial_password_hash: ""  # BCrypt hash (generate with: python -c "import bcrypt; print(bcrypt.hashpw(b'password', bcrypt.gensalt()).decode())")
fastdeploy_postgres_password: ""   # PostgreSQL password for FastDeploy database
```

### Common Configuration

Frequently modified settings with sensible defaults:

```yaml
# API and WebSocket URLs
fastdeploy_api_url: "https://deploy.example.com"
fastdeploy_websocket_url: "wss://deploy.example.com/deployments/ws"

# Initial admin user
fastdeploy_initial_user: "admin"

# Traefik configuration
fastdeploy_traefik_enabled: true
fastdeploy_traefik_host: "deploy.example.com"

# Application settings
fastdeploy_app_port: 9999
fastdeploy_workers: 4

# Python / uv
fastdeploy_python_version: "3.14"
```

### Advanced Configuration

```yaml
# User and paths
fastdeploy_user: "fastdeploy"
fastdeploy_home: "/home/fastdeploy"
fastdeploy_site_path: "{{ fastdeploy_home }}/site"

# Database configuration
fastdeploy_postgres_database: "fastdeploy"
fastdeploy_postgres_user: "fastdeploy"

# Feature flags
fastdeploy_build_frontend: true
fastdeploy_create_initial_user: true
fastdeploy_sync_services: true
```

For a complete list of variables, see `defaults/main.yml`.

### PostgreSQL Provisioning

The role automatically pulls in `local.ops_library.postgres_install` to install and configure PostgreSQL. Customize the forwarded settings via:

```yaml
fastdeploy_postgres_version: "17"
fastdeploy_postgres_packages:
  - "postgresql-{{ fastdeploy_postgres_version }}"
  - "postgresql-client-{{ fastdeploy_postgres_version }}"
  - "postgresql-contrib-{{ fastdeploy_postgres_version }}"
  - libpq-dev
fastdeploy_postgres_repo_enabled: true
fastdeploy_postgres_repo_url: https://apt.postgresql.org/pub/repos/apt
fastdeploy_postgres_repo_codename: "{{ ansible_distribution_release | default('jammy') }}"
fastdeploy_postgres_repo_components:
  - main
fastdeploy_postgres_repo_keyring: /etc/apt/keyrings/postgresql.asc
fastdeploy_postgres_repo_key_url: https://www.postgresql.org/media/keys/ACCC4CF8.asc
```

The dependency ensures the `fastdeploy_postgres_database` and `fastdeploy_postgres_user` are created before the application runs migrations.

### Traefik Dual Router Authentication

The role implements a dual router pattern for security:

- **Internal router** (priority 120): LAN and Tailscale clients bypass basic auth
  - IP ranges: RFC1918 private networks, Tailscale CGNAT (100.64.0.0/10), Tailscale IPv6 (fd7a::/48)
- **External router** (priority 100): Public internet requires basic auth
  - Uses shared credentials from `secrets/prod/traefik.yml`

This is **mandatory** for public-facing deployments per security policy.

**Configuration:**

```yaml
fastdeploy_basic_auth_enabled: true  # Default: true
fastdeploy_basic_auth_user: "admin"
fastdeploy_basic_auth_password: "{{ traefik_secrets.basic_auth_password }}"  # Plain text, will be hashed
fastdeploy_internal_ip_ranges:  # Customize for your network
  - "192.168.0.0/16"
  - "100.64.0.0/10"
  - "YOUR_IPV6_PREFIX::/64"
```

**Note:** The role expects a plain-text password in `fastdeploy_basic_auth_password`. It will automatically generate the bcrypt hash using `htpasswd` during deployment. Do NOT provide a pre-hashed password.

**Testing:**
- From LAN (192.168.x): No auth prompt
- From Tailscale (100.x): No auth prompt
- From public internet: Basic auth prompt appears

## Dependencies

This role automatically depends on `local.ops_library.postgres_install` to install PostgreSQL and provision the FastDeploy database/user.

## Example Playbook

### Basic Usage

```yaml
- name: Deploy FastDeploy
  hosts: production
  become: true
  vars:
    secrets: "{{ lookup('community.sops.sops', 'secrets/prod/fastdeploy.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.fastdeploy_deploy
      vars:
        fastdeploy_source_path: "/Users/john/projects/fastdeploy"
        fastdeploy_secret_key: "{{ secrets.django_secret_key }}"
        fastdeploy_initial_password_hash: "{{ secrets.admin_password_hash }}"
        fastdeploy_postgres_password: "{{ secrets.db_password }}"
```

### Advanced Usage with Custom Configuration

```yaml
- name: Deploy FastDeploy with Custom Settings
  hosts: production
  become: true
  vars:
    sops_secrets: "{{ lookup('community.sops.sops', 'secrets/prod/fastdeploy.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.fastdeploy_deploy
      vars:
        # Required secrets
        fastdeploy_source_path: "/Users/john/projects/fastdeploy"
        fastdeploy_secret_key: "{{ sops_secrets.django_secret_key }}"
        fastdeploy_initial_password_hash: "{{ sops_secrets.admin_password_hash }}"
        fastdeploy_postgres_password: "{{ sops_secrets.db_password }}"

        # Custom configuration
        fastdeploy_app_port: 10000
        fastdeploy_workers: 8
        fastdeploy_api_url: "https://deploy.internal.example.com"
        fastdeploy_websocket_url: "wss://deploy.internal.example.com/deployments/ws"
        fastdeploy_traefik_host: "deploy.internal.example.com"
        fastdeploy_traefik_cert_resolver: "internal-ca"
```

## Deployment Execution Architecture

When FastDeploy triggers a service deployment, the following execution chain occurs:

```
FastDeploy Service (runs as: fastdeploy)
    │
    ├── sudo -u deploy  (via /etc/sudoers.d/fastdeploy)
    │       │
    │       └── /home/fastdeploy/site/services/<service>/deploy.sh
    │               │
    │               └── sudo /usr/bin/env ANSIBLE_HOST_KEY_CHECKING=False ansible-playbook ...
    │                       (via /etc/sudoers.d/apt_upgrade_<service>)
```

### Key Components

1. **fastdeploy user**: Runs the FastDeploy web service
2. **deploy user**: Executes deployment scripts with elevated privileges
3. **Sudoers rules**:
   - `/etc/sudoers.d/fastdeploy`: Allows `fastdeploy` to run deploy.sh scripts as `deploy`
   - `/etc/sudoers.d/apt_upgrade_*`: Allows `deploy` to run ansible-playbook as root

### For Remote Targets

When deploying to remote servers (e.g., apt_upgrade_staging):
- SSH keys are stored in `/home/deploy/.ssh/`
- The playbook specifies `ansible_ssh_private_key_file` to use these keys
- The deploy key's public key must be authorized on the target server

### Troubleshooting

If deployments fail, check:
1. **Sudoers**: `sudo -l -U fastdeploy` and `sudo -l -U deploy`
2. **SSH keys**: `ls -la /home/deploy/.ssh/`
3. **SSH connectivity**: `sudo -u deploy ssh -i /home/deploy/.ssh/id_ed25519 root@<target> echo OK`
4. **Ansible manually**: `sudo -u deploy sudo /usr/bin/env ANSIBLE_HOST_KEY_CHECKING=False ansible-playbook <playbook> -i <host>, -v`

## Handlers

This role provides the following handlers:

- `restart fastdeploy` - Restarts the FastDeploy systemd service
- `reload systemd` - Reloads systemd daemon configuration

## Tags

Available tags for selective execution:

- `fastdeploy_frontend` - Frontend build tasks
- `fastdeploy_service` - Systemd service configuration
- `fastdeploy_traefik` - Traefik reverse proxy configuration

## Testing

```bash
# Run role tests
cd /path/to/ops-library
just test-role fastdeploy_deploy
```

## Changelog

- **1.0.0** (2024-09-22): Initial release with rsync deployment support
- See [CHANGELOG.md](../../CHANGELOG.md) for full history

## License

MIT

## Author Information

Created for homelab automation - part of the ops-library collection.
