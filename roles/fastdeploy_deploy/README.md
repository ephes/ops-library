# FastDeploy Deploy Role

Deploy the FastDeploy web-based deployment platform with full database, frontend, and service management.

## Description

This role deploys FastDeploy, a web-based platform for managing service deployments. It handles the complete deployment lifecycle including:
- PostgreSQL database setup and migrations
- Python environment management with uv
- Frontend application building
- Systemd service configuration
- Traefik reverse proxy integration
- Initial admin user creation
- Service synchronization from filesystem

## Requirements

- Ubuntu/Debian-based target system
- PostgreSQL installed and running
- Node.js 16+ (for frontend build)
- Python 3.8+
- Ansible 2.9+
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

## Dependencies

None.

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

## Handlers

This role provides the following handlers:

- `restart fastdeploy` - Restarts the FastDeploy systemd service
- `reload systemd` - Reloads systemd daemon configuration

## Tags

Available tags for selective execution:

- `fastdeploy_database` - Database setup tasks
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